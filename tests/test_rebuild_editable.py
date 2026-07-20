import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from rfs.cli import main
from rfs.editable_rebuild import economy_acceptance_decision, rebuild_editable
from rfs.professional_dsl import validate_and_normalize_dsl
from rfs.professional_repair import apply_professional_dsl_patch
from rfs.professional_rebuild import rebuild_editable_pro
from rfs.rebuild_eval import evaluate_rebuild_vlm
from rfs.rebuild_vlm_validation import build_rebuild_vlm_validation_report
from rfs.rebuild_vlm_adapters import build_rebuild_vlm_adapters, vlm_layout_adapter, vlm_semantic_adapter


def _fixture(path: Path) -> Path:
    image = Image.new("RGB", (640, 360), "#F7F3EA")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((30, 50, 610, 315), radius=20, fill="#FFFFFF", outline="#4A90C2", width=4)
    draw.rectangle((42, 72, 170, 170), fill="#DCEEFF", outline="#4A90C2", width=3)
    draw.ellipse((265, 88, 365, 188), fill="#F8D7A8", outline="#D28A2E", width=3)
    draw.rounded_rectangle((470, 78, 575, 178), radius=12, fill="#DDEEDB", outline="#4D9A57", width=3)
    draw.line((175, 120, 260, 120), fill="#333333", width=4)
    draw.polygon([(260, 120), (246, 112), (246, 128)], fill="#333333")
    draw.line((370, 130, 465, 130), fill="#333333", width=4)
    draw.polygon([(465, 130), (451, 122), (451, 138)], fill="#333333")
    draw.text((42, 22), "Pipeline Demo", fill="#1E2A33")
    draw.text((60, 190), "Input", fill="#1E2A33")
    draw.text((288, 205), "Agent", fill="#1E2A33")
    draw.text((492, 192), "Output", fill="#1E2A33")
    image.save(path)
    return path


class RebuildEditableTests(unittest.TestCase):
    def test_cli_placeholder_run_writes_required_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"
            with patch.dict("os.environ", {"API_BASE": "", "API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
                code = main(["rebuild-editable", "--reference", str(reference), "--out", str(out), "--asset-mode", "placeholder", "--text-mode", "off", "--export-preview"])
            self.assertEqual(code, 0)
            required = [
                "input_manifest.json",
                "reference_geometry.json",
                "reference_geometry_overlay.png",
                "rebuild_vlm_validation_report.json",
                "reference_text_geometry.json",
                "reference_controls.json",
                "reference_controls_overlay.png",
                "slot_inventory.json",
                "slot_semantic_report.json",
                "asset_generation_specs.json",
                "asset_generation_report.json",
                "asset_economy_report.json",
                "asset_ratio_fit_report.json",
                "figure_program.json",
                "composition_quality_report.json",
                "editable_composition.pptx",
            ]
            for name in required:
                self.assertTrue((out / name).exists(), name)
            self.assertTrue((out / "rebuild_preview.png").exists() or (out / "preview_export_error.txt").exists())
            with zipfile.ZipFile(out / "editable_composition.pptx") as archive:
                slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertNotIn("inputs/pipeline.png", slide_xml)
            self.assertIn("<p:pic>", slide_xml)
            self.assertIn("<p:cxnSp>", slide_xml)

    def test_fake_ocr_text_becomes_editable_textbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_ocr(_path, _lang):
                return [{
                    "text": "Pipeline Demo",
                    "confidence": 0.98,
                    "quad": [[40, 20], [210, 20], [210, 45], [40, 45]],
                }]

            result = rebuild_editable(reference, out, asset_mode="placeholder", text_mode="ocr", export_preview=False, ocr_adapter=fake_ocr)
            self.assertTrue(result["ok"])
            text_geometry = json.loads((out / "reference_text_geometry.json").read_text(encoding="utf-8"))
            self.assertEqual(text_geometry["detection_mode"], "ocr")
            self.assertEqual(text_geometry["text_regions"][0]["raw_text"], "Pipeline Demo")
            with zipfile.ZipFile(out / "editable_composition.pptx") as archive:
                slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertIn("Pipeline Demo", slide_xml)

    def test_fake_vlm_layout_enters_geometry_and_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_layout(_path, _base):
                return {
                    "confidence": 0.93,
                    "panels": [{"id": "stage_a", "title": "Stage A", "bbox_percent": {"x": 0.04, "y": 0.10, "w": 0.92, "h": 0.78}}],
                    "slots": [
                        {"id": "input_doc", "asset_id": "input_doc", "bbox_percent": {"x": 0.08, "y": 0.25, "w": 0.18, "h": 0.24}, "prompt_subject": "input document"},
                        {"id": "ai_critic", "asset_id": "ai_critic", "bbox_percent": {"x": 0.42, "y": 0.24, "w": 0.16, "h": 0.28}, "prompt_subject": "AI Critic robot"},
                        {"id": "output_card", "asset_id": "output_card", "bbox_percent": {"x": 0.72, "y": 0.25, "w": 0.18, "h": 0.24}, "prompt_subject": "output card"},
                    ],
                }

            result = rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off", vlm_layout_adapter=fake_layout)
            self.assertTrue(result["ok"])
            geometry = json.loads((out / "reference_geometry.json").read_text(encoding="utf-8"))
            program = json.loads((out / "figure_program.json").read_text(encoding="utf-8"))
            self.assertEqual(geometry["vlm_status"], "used")
            self.assertEqual(geometry["confidence"], 0.93)
            self.assertEqual([slot["id"] for slot in program["slots"]], ["input_doc", "ai_critic", "output_card"])

    def test_fake_control_localizer_path_is_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_layout(_path, _base):
                return {
                    "slots": [
                        {"id": "slot_a", "asset_id": "slot_a", "bbox_percent": {"x": 0.10, "y": 0.25, "w": 0.16, "h": 0.22}},
                        {"id": "slot_b", "asset_id": "slot_b", "bbox_percent": {"x": 0.70, "y": 0.25, "w": 0.16, "h": 0.22}},
                    ]
                }

            def fake_controls(_path, _slots, _heuristic):
                return {"arrows": [{
                    "id": "detected_arrow",
                    "source_id": "slot_a",
                    "target_id": "slot_b",
                    "control_kind": "elbow_connector",
                    "path_percent": [[0.26, 0.36], [0.50, 0.36], [0.50, 0.50], [0.70, 0.50]],
                    "stroke_color": "#D94141",
                    "stroke_width_pt": 2.0,
                    "dash_style": "solid",
                    "confidence": 0.91,
                }]}

            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off", vlm_layout_adapter=fake_layout, control_adapter=fake_controls)
            controls = json.loads((out / "reference_controls.json").read_text(encoding="utf-8"))
            self.assertEqual(controls["vlm_status"], "used")
            self.assertEqual(controls["arrows"][0]["path_percent"][1], [0.5, 0.36])
            report = json.loads((out / "composition_quality_report.json").read_text(encoding="utf-8"))
            rendered = {item["arrow_id"]: item for item in report["arrows"]}
            self.assertEqual(rendered["detected_arrow"]["segment_count"], 3)

    def test_ocr_nearby_text_influences_slot_semantics_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_layout(_path, _base):
                return {"slots": [{"id": "critic_icon", "asset_id": "critic_icon", "bbox_percent": {"x": 0.40, "y": 0.20, "w": 0.18, "h": 0.30}}]}

            def fake_ocr(_path, _lang):
                return [{"text": "AI Critic", "confidence": 0.99, "quad": [[260, 80], [370, 80], [370, 112], [260, 112]]}]

            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="ocr", vlm_layout_adapter=fake_layout, ocr_adapter=fake_ocr)
            inventory = json.loads((out / "slot_inventory.json").read_text(encoding="utf-8"))
            slot = inventory["slots"][0]
            self.assertEqual(slot["asset_type"], "character")
            self.assertIn("AI Critic", slot["prompt_subject"])
            specs = json.loads((out / "asset_generation_specs.json").read_text(encoding="utf-8"))
            self.assertEqual(specs["specs"][0]["asset_type"], "character")
            self.assertIn("AI Critic", specs["specs"][0]["prompt"])

    def test_economy_policy_is_type_aware_for_thin_tools(self):
        decision = economy_acceptance_decision("thin_tool", 0.62, strict=False)
        self.assertTrue(decision["accepted"])
        strict = economy_acceptance_decision("thin_tool", 0.62, strict=True)
        self.assertFalse(strict["accepted"])

    def test_accepted_existing_assets_avoid_api_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"
            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off")
            first = json.loads((out / "asset_generation_report.json").read_text(encoding="utf-8"))
            self.assertEqual(first["api_requests_attempted"], 0)
            accepted = {item["slot_id"]: {"accepted": True} for item in first["assets"]}
            (out / "accepted_assets.json").write_text(json.dumps(accepted), encoding="utf-8")
            rebuild_editable(reference, out, asset_mode="api", text_mode="off")
            second = json.loads((out / "asset_generation_report.json").read_text(encoding="utf-8"))
            self.assertEqual(second["api_requests_attempted"], 0)

    def test_compile_only_rebuilds_from_existing_contracts_without_assets_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"
            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off")
            report_before = json.loads((out / "asset_generation_report.json").read_text(encoding="utf-8"))
            result = rebuild_editable(reference, out, asset_mode="api", text_mode="off", compile_only=True)
            self.assertTrue(result["compile_only"])
            report_after = json.loads((out / "asset_generation_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report_before["api_requests_attempted"], report_after["api_requests_attempted"])
            self.assertTrue((out / "editable_composition.pptx").exists())

    def test_vlm_validation_report_flags_bad_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            geometry = {
                "layout_mode": "hybrid",
                "vlm_status": "used",
                "panels": [{"id": "panel_a", "bbox_percent": {"x": 0, "y": 0, "w": 1, "h": 1}}],
                "slots": [
                    {"id": "slot_a", "bbox_percent": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "bbox_was_clamped": True},
                    {"id": "slot_a", "bbox_percent": {"x": 1.2, "y": 0.1, "w": 0.2, "h": 0.2}},
                ],
                "cards": [],
                "legend_regions": [],
            }
            controls = {"mode": "hybrid", "vlm_status": "used", "arrows": [{"id": "bad_arrow", "source_id": "missing", "target_id": "slot_a", "path_percent": [[0.1, 0.1]]}]}
            semantic = {"semantic_vlm_status": "used", "slots": [{"slot_id": "slot_a", "asset_type": "not_real", "prompt_subject": ""}]}
            report = build_rebuild_vlm_validation_report(out, geometry, controls, semantic, {"asset_mode": "crop", "api_requests_attempted": 0})
            self.assertEqual(report["status"], "warning")
            self.assertIn("slot_a", report["layout"]["duplicate_slot_ids"])
            self.assertIn("slot_a", report["layout"]["clamped_bbox_ids"])
            self.assertIn("bad_arrow", report["control"]["invalid_arrow_ids"])
            self.assertIn("slot_a", report["semantic"]["invalid_asset_type_ids"])

    def test_real_vlm_layout_adapter_uses_shared_client_and_model_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            with patch.dict("os.environ", {"RFS_REBUILD_LAYOUT_MODEL": "layout-model"}, clear=False):
                with patch("rfs.rebuild_vlm_adapters.call_vlm_json") as call:
                    call.return_value = {"confidence": 0.9, "panels": [], "slots": []}
                    result = vlm_layout_adapter(reference, {"slots": []})
            self.assertEqual(result["confidence"], 0.9)
            self.assertEqual(call.call_args.kwargs["model"], "layout-model")
            self.assertEqual(call.call_args.args[1], [reference])

    def test_real_vlm_semantic_adapter_output_can_drive_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_layout(_path, _base):
                return {"slots": [{"id": "slot_robot", "asset_id": "slot_robot", "bbox_percent": {"x": 0.35, "y": 0.20, "w": 0.18, "h": 0.30}}]}

            def fake_semantic(_path, _slots, _panels, _controls, _text_geometry):
                return {"slots": [{"slot_id": "slot_robot", "asset_type": "character", "semantic_role": "robot_agent", "prompt_subject": "friendly robot agent", "nearby_text": ["Agent"]}]}

            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off", vlm_layout_adapter=fake_layout, semantic_adapter=fake_semantic)
            spec = json.loads((out / "asset_generation_specs.json").read_text(encoding="utf-8"))["specs"][0]
            self.assertEqual(spec["asset_type"], "character")
            self.assertIn("friendly robot agent", spec["prompt"])

    def test_invalid_semantic_asset_type_falls_back_to_generic_and_reports_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_layout(_path, _base):
                return {"slots": [{"id": "slot_unknown", "asset_id": "slot_unknown", "bbox_percent": {"x": 0.35, "y": 0.20, "w": 0.18, "h": 0.30}}]}

            def fake_semantic(_path, _slots, _panels, _controls, _text_geometry):
                return {"slots": [{"slot_id": "slot_unknown", "asset_type": "nonsense_type", "prompt_subject": "unknown object"}]}

            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off", vlm_layout_adapter=fake_layout, semantic_adapter=fake_semantic)
            inventory = json.loads((out / "slot_inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(inventory["slots"][0]["asset_type"], "generic")
            semantic = json.loads((out / "slot_semantic_report.json").read_text(encoding="utf-8"))
            self.assertEqual(semantic["invalid_asset_type_count"], 1)

    def test_invalid_vlm_control_arrow_is_dropped_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "rebuild"

            def fake_layout(_path, _base):
                return {"slots": [
                    {"id": "slot_a", "asset_id": "slot_a", "bbox_percent": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.2}},
                    {"id": "slot_b", "asset_id": "slot_b", "bbox_percent": {"x": 0.6, "y": 0.2, "w": 0.2, "h": 0.2}},
                ]}

            def fake_controls(_path, _slots, _heuristic):
                return {"arrows": [
                    {"id": "invalid", "source_id": "missing", "target_id": "slot_b", "path_percent": [[0.1, 0.1], [0.2, 0.2]]},
                    {"id": "valid", "source_id": "slot_a", "target_id": "slot_b", "path_percent": [[0.3, 0.3], [0.6, 0.3]]},
                ]}

            rebuild_editable(reference, out, asset_mode="placeholder", text_mode="off", vlm_layout_adapter=fake_layout, control_adapter=fake_controls)
            controls = json.loads((out / "reference_controls.json").read_text(encoding="utf-8"))
            self.assertEqual([arrow["id"] for arrow in controls["arrows"]], ["valid"])
            self.assertTrue(any("invalid_vlm_control" in warning for warning in controls["warnings"]))

    def test_rebuild_editable_eval_runs_crop_without_image_api_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            with patch.dict("os.environ", {"API_BASE": "", "API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
                summary = evaluate_rebuild_vlm(reference, root / "eval", asset_mode="crop", text_mode="off", export_preview=False)
            self.assertTrue(summary["ok"])
            self.assertFalse(summary["image_generation_api_expected"])
            self.assertEqual(summary["cases"]["heuristic"]["api_requests_attempted"], 0)
            self.assertEqual(summary["cases"]["vlm"]["api_requests_attempted"], 0)
            self.assertTrue((root / "eval" / "rebuild_vlm_eval_summary.json").exists())

    def test_rebuild_vlm_adapter_factory_requires_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"API_BASE": "", "API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
                adapters = build_rebuild_vlm_adapters(tmp)
            self.assertIsNone(adapters["layout"])
            with patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "key"}, clear=False):
                adapters = build_rebuild_vlm_adapters(tmp)
            self.assertIsNotNone(adapters["layout"])
            self.assertIsNotNone(adapters["control"])
            self.assertIsNotNone(adapters["semantic"])

    def test_cli_professional_placeholder_run_writes_dsl_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "pro"
            with patch.dict("os.environ", {"API_BASE": "", "API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
                code = main(["rebuild-editable-pro", "--reference", str(reference), "--out", str(out), "--asset-mode", "placeholder", "--text-mode", "off", "--repair-rounds", "1", "--export-preview"])
            self.assertEqual(code, 0)
            required = [
                "professional_rebuild_plan.json",
                "professional_rebuild_script.dsl.json",
                "professional_rebuild_validation.json",
                "professional_rebuild_notes.md",
                "professional_repair_round_1.json",
                "figure_program.json",
                "asset_generation_specs.json",
                "editable_composition.pptx",
            ]
            for name in required:
                self.assertTrue((out / name).exists(), name)
            validation = json.loads((out / "professional_rebuild_validation.json").read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "pass")
            with zipfile.ZipFile(out / "editable_composition.pptx") as archive:
                slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertNotIn("inputs/pipeline.png", slide_xml)
            self.assertIn("<p:pic>", slide_xml)

    def test_professional_fake_planner_dsl_compiles_text_arrow_and_asset_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "pro"

            def fake_planner(_reference, _baseline, _text_geometry):
                return {
                    "summary": "fake professional script",
                    "dsl_version": "1.0",
                    "canvas": {"width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                    "objects": [
                        {"type": "canvas", "id": "canvas", "width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                        {"type": "style_tokens", "id": "style_tokens", "font_family": "Arial", "palette": ["#F7F3EA", "#4A90C2"]},
                        {"type": "panel", "id": "main_panel", "title": "Main", "bbox_percent": {"x": 0.04, "y": 0.12, "w": 0.92, "h": 0.76}, "fill_color": "#FFFFFF", "stroke_color": "#4A90C2"},
                        {"type": "text", "id": "title_text", "text": "Pipeline Demo", "bbox_percent": {"x": 0.06, "y": 0.04, "w": 0.4, "h": 0.08}, "font_size_pt": 18, "bold": True, "align": "left"},
                        {"type": "asset_slot", "id": "robot_icon", "asset_id": "robot_icon", "bbox_percent": {"x": 0.40, "y": 0.25, "w": 0.18, "h": 0.30}, "asset_type": "character", "prompt_subject": "friendly robot agent", "background_color_hex": "#FFFFFF", "generation_aspect_ratio": "3:4"},
                        {"type": "polyline", "id": "flow_arrow", "source_id": "robot_icon", "target_id": "robot_icon", "path_percent": [[0.20, 0.30], [0.55, 0.30], [0.70, 0.42]], "stroke_color": "#D94141", "stroke_width_pt": 2.4},
                    ],
                }

            result = rebuild_editable_pro(reference, out, asset_mode="placeholder", text_mode="off", export_preview=False, repair_rounds=0, planner_adapter=fake_planner)
            self.assertTrue(result["ok"])
            self.assertEqual(result["text_count"], 1)
            self.assertEqual(result["connector_count"], 1)
            specs = json.loads((out / "asset_generation_specs.json").read_text(encoding="utf-8"))
            self.assertEqual(specs["specs"][0]["generation_aspect_ratio"], "3:4")
            self.assertIn("friendly robot agent", specs["specs"][0]["prompt"])
            with zipfile.ZipFile(out / "editable_composition.pptx") as archive:
                slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertIn("Pipeline Demo", slide_xml)
            report = json.loads((out / "composition_quality_report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["no_full_image_policy"]["contains_full_reference_image"])
            gap = json.loads((out / "professional_gap_report.json").read_text(encoding="utf-8"))
            self.assertEqual(gap["professional_counts"]["text_count"], 1)
            self.assertEqual(gap["professional_counts"]["connector_count"], 1)

    def test_professional_invalid_dsl_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            dsl = {
                "canvas": {"width_px": 640, "height_px": 360, "width_in": 12, "height_in": 6.75},
                "objects": [
                    {"type": "asset_slot", "id": "dup", "bbox_percent": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}},
                    {"type": "asset_slot", "id": "dup", "bbox_percent": {"x": 0.3, "y": 0.1, "w": 0.2, "h": 0.2}},
                    {"type": "arrow", "id": "bad_arrow", "source_id": "dup", "target_id": "dup"},
                    {"type": "unknown", "id": "bad", "bbox_percent": {"x": 0, "y": 0, "w": 1, "h": 1}},
                ],
            }
            _normalized, report = validate_and_normalize_dsl(dsl, reference, root / "out")
            self.assertEqual(report["status"], "error")
            self.assertTrue(any("duplicate id dup" in error for error in report["errors"]))
            self.assertTrue(any("bad_arrow missing at least two" in error for error in report["errors"]))
            self.assertTrue(any("unknown object type" in error for error in report["errors"]))

    def test_professional_compile_only_reuses_existing_dsl_without_planner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "pro"

            def fake_planner(_reference, _baseline, _text_geometry):
                return {
                    "canvas": {"width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                    "objects": [
                        {"type": "canvas", "id": "canvas", "width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                        {"type": "asset_slot", "id": "slot_a", "asset_id": "slot_a", "bbox_percent": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.3}, "prompt_subject": "document card"},
                    ],
                }

            first = rebuild_editable_pro(reference, out, asset_mode="placeholder", text_mode="off", repair_rounds=0, planner_adapter=fake_planner)
            self.assertTrue(first["ok"])
            with patch("rfs.professional_rebuild.plan_professional_dsl") as planner:
                second = rebuild_editable_pro(reference, out, asset_mode="placeholder", text_mode="off", compile_only=True, repair_rounds=0)
            planner.assert_not_called()
            self.assertTrue(second["compile_only"])
            self.assertTrue((out / "editable_composition.pptx").exists())

    def test_professional_benchmark_gap_report_compares_specialized_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            benchmark = root / "benchmark"
            benchmark.mkdir()
            (benchmark / "figure_program.json").write_text(json.dumps({
                "panels": [{"id": "p"}],
                "cards": [{"id": "c1"}, {"id": "c2"}],
                "slots": [{"id": "s"}],
                "assets": [{"id": "s"}],
                "arrows": [{"id": "a1"}, {"id": "a2"}],
                "text_program": {"items": [{"id": "t1"}, {"id": "t2"}]},
                "labels": [],
            }), encoding="utf-8")

            def fake_planner(_reference, _baseline, _text_geometry):
                return {
                    "canvas": {"width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                    "objects": [
                        {"type": "canvas", "id": "canvas", "width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                        {"type": "text", "id": "t", "text": "Only one", "bbox_percent": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}},
                    ],
                }

            out = root / "pro"
            rebuild_editable_pro(reference, out, asset_mode="placeholder", text_mode="off", repair_rounds=0, planner_adapter=fake_planner, benchmark_out=benchmark)
            gap = json.loads((out / "professional_gap_report.json").read_text(encoding="utf-8"))
            self.assertEqual(gap["benchmark_counts"]["text_count"], 2)
            self.assertIn("professional_text_count_below_benchmark", gap["risks"])

    def test_professional_repair_patch_only_allows_safe_fields(self):
        dsl = {"objects": [{"type": "text", "id": "title", "text": "Demo", "font_size_pt": 10}]}
        patched, report = apply_professional_dsl_patch(dsl, {
            "operations": [
                {"op": "replace", "object_id": "title", "field": "font_size_pt", "value": 13},
                {"op": "replace", "object_id": "title", "field": "text", "value": "Bad"},
                {"op": "add", "object_id": "new", "field": "font_size_pt", "value": 9},
            ]
        })
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["applied_count"], 1)
        self.assertEqual(patched["objects"][0]["font_size_pt"], 13)
        self.assertEqual(patched["objects"][0]["text"], "Demo")

    def test_professional_repair_adapter_patches_dsl_and_recompiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "pro"

            def fake_planner(_reference, _baseline, _text_geometry):
                return {
                    "canvas": {"width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                    "objects": [
                        {"type": "canvas", "id": "canvas", "width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                        {"type": "text", "id": "title", "text": "Pipeline Demo", "bbox_percent": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.1}, "font_size_pt": 10},
                    ],
                }

            def fake_repair(_reference, _preview, _dsl, _round):
                return {"operations": [{"op": "replace", "object_id": "title", "field": "font_size_pt", "value": 14}]}

            result = rebuild_editable_pro(reference, out, asset_mode="placeholder", text_mode="off", repair_rounds=1, planner_adapter=fake_planner, repair_adapter=fake_repair)
            self.assertTrue(result["ok"])
            patched = json.loads((out / "professional_rebuild_script.dsl.json").read_text(encoding="utf-8"))
            title = next(obj for obj in patched["objects"] if obj["id"] == "title")
            self.assertEqual(title["font_size_pt"], 14)
            repair = json.loads((out / "professional_repair_round_1.json").read_text(encoding="utf-8"))
            self.assertEqual(repair["applied_count"], 1)

    def test_smart_api_policy_filters_text_slots_and_disables_final_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "pro"

            def fake_planner(_reference, _baseline, _text_geometry):
                return {
                    "canvas": {"width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                    "objects": [
                        {"type": "canvas", "id": "canvas", "width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                        {"type": "text", "id": "text_label", "text": "Output", "bbox_percent": {"x": 0.55, "y": 0.20, "w": 0.20, "h": 0.08}, "font_size_pt": 12},
                        {"type": "asset_slot", "id": "misread_text_as_icon", "asset_id": "misread_text_as_icon", "bbox_percent": {"x": 0.55, "y": 0.20, "w": 0.20, "h": 0.08}, "asset_type": "generic", "prompt_subject": "Output text"},
                        {"type": "asset_slot", "id": "robot_icon", "asset_id": "robot_icon", "bbox_percent": {"x": 0.20, "y": 0.25, "w": 0.16, "h": 0.24}, "asset_type": "character", "prompt_subject": "friendly robot"},
                    ],
                }

            result = rebuild_editable_pro(reference, out, asset_mode="crop", asset_policy="smart-api", text_mode="off", repair_rounds=0, planner_adapter=fake_planner)
            self.assertTrue(result["ok"])
            self.assertEqual(result["asset_policy"], "smart-api")
            report = json.loads((out / "asset_generation_report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["final_crop_assets_allowed"])
            statuses = {item["slot_id"]: item["status"] for item in report["assets"]}
            self.assertEqual(statuses["robot_icon"], "crop_disabled_by_smart_api_policy_placeholder")
            self.assertNotIn("misread_text_as_icon", statuses)
            text_filter = json.loads((out / "text_asset_filter_report.json").read_text(encoding="utf-8"))
            self.assertEqual(text_filter["items"][0]["candidate_id"], "misread_text_as_icon")
            program = json.loads((out / "figure_program.json").read_text(encoding="utf-8"))
            self.assertEqual([slot["id"] for slot in program["slots"]], ["robot_icon"])

    def test_smart_api_policy_reuses_duplicate_complex_icons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = _fixture(root / "pipeline.png")
            out = root / "pro"

            def fake_planner(_reference, _baseline, _text_geometry):
                return {
                    "canvas": {"width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                    "objects": [
                        {"type": "canvas", "id": "canvas", "width_px": 640, "height_px": 360, "width_in": 12.0, "height_in": 6.75, "background": "#F7F3EA"},
                        {"type": "asset_slot", "id": "executor_a_icon", "asset_id": "executor_a_icon", "bbox_percent": {"x": 0.20, "y": 0.25, "w": 0.12, "h": 0.18}, "asset_type": "tool_combo", "prompt_subject": "terminal and database icon"},
                        {"type": "asset_slot", "id": "executor_b_icon", "asset_id": "executor_b_icon", "bbox_percent": {"x": 0.40, "y": 0.25, "w": 0.12, "h": 0.18}, "asset_type": "tool_combo", "prompt_subject": "terminal and database icon"},
                    ],
                }

            with patch.dict("os.environ", {"API_BASE": "", "API_KEY": "", "GEMINI_API_KEY": "", "GEMINI_GEN_IMG_URL": ""}, clear=False):
                result = rebuild_editable_pro(reference, out, asset_mode="api", asset_policy="smart-api", text_mode="off", repair_rounds=0, planner_adapter=fake_planner)
            self.assertTrue(result["ok"])
            report = json.loads((out / "asset_generation_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["api_requests_attempted"], 1)
            statuses = {item["slot_id"]: item["status"] for item in report["assets"]}
            self.assertEqual(statuses["executor_a_icon"], "api_failed_placeholder_fallback")
            self.assertEqual(statuses["executor_b_icon"], "reused_from_group")
            plan = json.loads((out / "api_asset_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["unique_api_assets"], 1)
            self.assertEqual(plan["reused_slots"], 1)


if __name__ == "__main__":
    unittest.main()
