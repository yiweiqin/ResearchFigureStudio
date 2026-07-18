import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from rfs.cli import main
from rfs.editable_rebuild import economy_acceptance_decision, rebuild_editable
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


if __name__ == "__main__":
    unittest.main()
