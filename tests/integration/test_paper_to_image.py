from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import requests
from PIL import Image

from rfs.cli import _doctor, _probe_executable, build_parser
from rfs.paper_to_image import run_fast_framework_prompt, run_paper_to_image
from rfs.paper_to_image.critics import required_labels, review_candidate
from rfs.paper_to_image.generator import generate_and_select, native_image2_aspect_ratio
from rfs.paper_to_image.planner import collect_visual_relations, compile_image_prompt
from rfs.paper_to_image.review import detect_domain_profile, validate_review_coverage
from rfs.paper_to_image.templates import build_template_profiles, render_layout_blueprint, select_template


PAPER_TEXT = """
Evidence-Grounded Modular Reasoning for Scientific Documents

Abstract
We introduce ModularTrace, a method that converts scientific documents into an evidence graph and then performs constrained reasoning over the graph. The method reduces unsupported conclusions while preserving exact paper terminology.

1 Introduction
Scientific document assistants often generate claims without traceable evidence. ModularTrace addresses this problem by linking every extracted fact to a source passage.

2 Method
The Document Parser splits the input paper into page-aware passages. The Evidence Graph Builder extracts entities and directed relations. The Constrained Reasoner consumes the graph and produces an answer with evidence identifiers. During training, a consistency loss penalizes unsupported relations. During inference, only retrieved evidence nodes may support an answer.

3 Experiments
We evaluate on three scientific question-answering datasets using answer accuracy and evidence precision.

4 Conclusion
ModularTrace improves evidence precision while maintaining answer accuracy.
""".strip()


def _png_b64(size=(1536, 1024), color=(235, 242, 247)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"b64_json": _png_b64()}]}


def _passing_critic(_path, _blueprint, _prompt):
    return {
        "summary": "Mock passing critic.",
        "ocr": {"detected_labels": ["Document Parser", "Evidence Graph Builder"], "missing_labels": [], "misspelled_labels": [], "duplicate_labels": [], "forbidden_labels_found": [], "score": 1.0, "passed": True},
        "scientific": {"missing_modules": [], "missing_relations": [], "reversed_relations": [], "invented_items": [], "innovation_visible": True, "score": 1.0, "passed": True},
        "template": {"macro_panel_match": 0.9, "reading_order_match": 0.9, "connector_rhythm_match": 0.9, "visual_density_match": 0.9, "copied_reference_content": [], "score": 0.9, "passed": True},
        "aesthetic": {"hierarchy": 0.9, "balance": 0.9, "whitespace": 0.9, "color": 0.9, "icon_consistency": 0.9, "readability": 0.9, "score": 0.9, "passed": True},
        "preserve": ["macro layout"],
        "repair": [],
        "remove": [],
        "repair_regions": [],
        "hard_errors": [],
    }


def _plan() -> dict:
    modules = [
        {"id": "parser", "name": "Document Parser", "role": "module", "evidence_ids": ["E0001"]},
        {"id": "graph", "name": "Evidence Graph Builder", "role": "module", "evidence_ids": ["E0001"]},
    ]
    return {
        "paper_summary": {"summary": "Paper summary.", "title": "ModularTrace"},
        "figure_specification": {"summary": "Scientific contract.", "figure_goal": "Show the method.", "modules": modules, "relations": [{"source": "parser", "target": "graph", "type": "data_flow", "evidence_ids": ["E0001"]}], "terminology": {"Document Parser": "Document Parser", "Evidence Graph Builder": "Evidence Graph Builder"}, "forbidden_inventions": []},
        "design_plan": {"summary": "Design.", "reading_order": ["parser", "graph"]},
        "layout_intent": {"summary": "Layout.", "pattern": "left_to_right"},
        "visual_metaphors": {"summary": "Metaphors.", "items": []},
        "style_plan": {"summary": "Style.", "medium": "academic"},
    }


class PaperToImageTests(unittest.TestCase):
    def test_offline_workflow_is_engineering_only(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_KEY": "known-test-secret"}, clear=False):
            root = Path(temp)
            paper = root / "paper.md"
            paper.write_text(PAPER_TEXT, encoding="utf-8")
            out = root / "run"
            result = run_paper_to_image(paper=paper, out=out, planner_mode="heuristic", asset_mode="placeholder", candidates=2, aspect_ratio="auto", review_mode="heuristic", ocr_engine="off")

            self.assertTrue(result["ok"])
            self.assertFalse(result["pptx_generated"])
            self.assertEqual(result["candidate_count"], 2)
            self.assertIsNone(result["selected_image"])
            self.assertTrue((out / "engineering_preview.png").exists())
            self.assertFalse((out / "selected_image.png").exists())
            for name in ["document_index.json", "paper_review.json", "review_coverage_report.json", "domain_profile.json", "selected_template.json", "layout_blueprint.png", "image2_request_manifest.json", "ocr_review.json", "template_alignment_report.json", "scientific_critic_report.json", "aesthetic_critic_report.json"]:
                self.assertTrue((out / name).exists(), name)
            document_index = json.loads((out / "document_index.json").read_text(encoding="utf-8"))
            self.assertTrue(document_index["sections"])
            manifest = json.loads((out / "image2_request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["requests"][0]["model"], "offline-placeholder")
            self.assertIn("api_key_present", manifest)
            self.assertNotIn("known-test-secret", json.dumps(manifest))

    def test_cli_production_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["paper-to-image", "--paper", "paper.pdf", "--out", "output/run"])
        self.assertEqual(args.command, "paper-to-image")
        self.assertEqual(args.asset_mode, "image2")
        self.assertEqual(args.candidates, 3)
        self.assertEqual(args.review_mode, "vlm")
        self.assertEqual(args.aspect_ratio, "auto")
        self.assertEqual(args.domain_profile, "auto")
        self.assertEqual(args.template, "auto")
        self.assertEqual(args.repair_rounds, 1)

    def test_image2_native_canvas_ratio_normalization(self):
        self.assertEqual(native_image2_aspect_ratio("16:9"), "3:2")
        self.assertEqual(native_image2_aspect_ratio("9:16"), "2:3")
        self.assertEqual(native_image2_aspect_ratio("1:1"), "1:1")

    def test_prompt_and_critic_share_complete_visible_label_contract(self):
        plan = _plan()
        spec = plan["figure_specification"]
        spec.update({
            "required_labels": ["Input Matrix", "Document Parser", "Final Answer"],
            "inputs": [{"id": "input", "name": "Input Matrix"}],
            "outputs": [{"id": "answer", "name": "Final Answer"}],
            "innovations": [{"id": "grounding", "name": "Evidence Grounding"}],
        })

        labels = required_labels(plan)
        prompt = compile_image_prompt(plan, {"aspect_ratio": "16:9", "language": "English"})

        self.assertEqual(labels[:3], ["Input Matrix", "Document Parser", "Final Answer"])
        for label in ("Input Matrix", "Document Parser", "Final Answer"):
            self.assertIn(label, labels)
            self.assertIn(label, prompt)
        self.assertNotIn("Evidence Grounding", labels)
        self.assertIn("Evidence Grounding", prompt)
        self.assertIn("never replace an output label with an icon-only node", prompt)

    def test_visual_relation_checklist_deduplicates_edges_and_skips_shared_model_wiring(self):
        spec = {
            "inputs": [{"id": "input", "name": "Input"}],
            "modules": [
                {"id": "model", "name": "Model M"},
                {"id": "generate", "name": "Generate"},
                {"id": "initial", "name": "Initial Output"},
                {"id": "feedback", "name": "Feedback"},
                {"id": "refine", "name": "Refine"},
            ],
            "outputs": [{"id": "refined", "name": "Refined Output"}],
            "innovations": [],
            "repeatable_labels": ["Model M"],
            "relations": [
                {"source": "input", "target": "model", "type": "data_flow"},
                {"source": "model", "target": "initial", "type": "prediction"},
                {"source": "input", "target": "generate", "type": "generation_input"},
                {"source": "input", "target": "generate", "type": "data_flow"},
                {"source": "generate", "target": "initial", "type": "data_flow"},
                {"source": "initial", "target": "feedback", "type": "data_flow"},
                {"source": "initial", "target": "feedback", "type": "evaluation"},
                {"source": "initial", "target": "refine", "type": "revision_input"},
                {"source": "feedback", "target": "refine", "type": "feedback"},
                {"source": "refine", "target": "refined", "type": "prediction"},
                {"source": "refine", "target": "refined", "type": "data_flow"},
                {"source": "refined", "target": "feedback", "type": "feedback_loop"},
            ],
        }

        relations = collect_visual_relations(spec)
        pairs = {(item["source"], item["target"]): item["type"] for item in relations}

        self.assertNotIn(("input", "model"), pairs)
        self.assertNotIn(("model", "initial"), pairs)
        self.assertEqual(pairs[("input", "generate")], "data_flow")
        self.assertEqual(pairs[("initial", "feedback")], "evaluation")
        self.assertEqual(pairs[("refine", "refined")], "data_flow")
        self.assertEqual(pairs[("refined", "feedback")], "feedback_loop")

    def test_candidate_review_accepts_requested_ratio_when_image2_ignores_blueprint_ratio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.png"
            blueprint = root / "blueprint.png"
            Image.new("RGB", (1600, 900), "white").save(candidate)
            Image.new("RGB", (1536, 1024), "white").save(blueprint)

            review = review_candidate(
                candidate,
                blueprint,
                _plan(),
                {"template_id": "linear", "forbidden_copy_terms": []},
                mode="vlm",
                ocr_engine="off",
                critic_adapter=_passing_critic,
                acceptable_aspect_ratios=["16:9", "3:2"],
            )

            self.assertTrue(review["basic"]["passed"])
            self.assertEqual(review["basic"]["matched_aspect_ratio"], "16:9")

    def test_candidate_review_allows_evidence_supported_shared_label_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.png"
            blueprint = root / "blueprint.png"
            Image.new("RGB", (1536, 1024), "white").save(candidate)
            Image.new("RGB", (1536, 1024), "white").save(blueprint)
            plan = _plan()
            plan["figure_specification"]["repeatable_labels"] = ["Document Parser"]

            def critic(path, template, prompt):
                result = _passing_critic(path, template, prompt)
                result["ocr"].update({"duplicate_labels": ["Document Parser"], "passed": False})
                result["hard_errors"] = ["Duplicate label: Document Parser", "Template mismatch: too many content nodes"]
                return result

            review = review_candidate(candidate, blueprint, plan, {"template_id": "linear", "forbidden_copy_terms": []}, mode="vlm", ocr_engine="off", critic_adapter=critic)

            self.assertTrue(review["production_pass"])
            self.assertEqual(review["ocr"]["allowed_duplicate_labels"], ["Document Parser"])
            self.assertEqual(review["ocr"]["duplicate_labels"], [])

    def test_candidate_review_rejects_visible_labels_outside_contract_whitelist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.png"
            blueprint = root / "blueprint.png"
            Image.new("RGB", (1536, 1024), "white").save(candidate)
            Image.new("RGB", (1536, 1024), "white").save(blueprint)

            def critic(path, template, prompt):
                result = _passing_critic(path, template, prompt)
                result["ocr"]["detected_labels"].append("Contrastive Loss")
                return result

            review = review_candidate(candidate, blueprint, _plan(), {"template_id": "linear", "forbidden_copy_terms": []}, mode="vlm", ocr_engine="off", critic_adapter=critic)

            self.assertFalse(review["production_pass"])
            self.assertEqual(review["ocr"]["unexpected_labels"], ["Contrastive Loss"])
            self.assertIn("Remove unexpected visible label: Contrastive Loss", review["repair"])
            self.assertIn("Contrastive Loss", review["remove"])

    def test_complex_feedback_candidate_requires_focused_topology_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.png"
            blueprint = root / "blueprint.png"
            Image.new("RGB", (1536, 1024), "white").save(candidate)
            Image.new("RGB", (1536, 1024), "white").save(blueprint)
            plan = _plan()
            plan["figure_specification"].update({
                "topology": "feedback",
                "inputs": [{"id": "input", "name": "Input"}],
                "modules": [{"id": "refine", "name": "Refine"}],
                "outputs": [{"id": "output", "name": "Refined Output"}],
                "relations": [{"source": "input", "target": "refine", "type": "revision_input"}, {"source": "refine", "target": "output", "type": "data_flow"}],
                "terminology": {},
            })

            topology = lambda _path, _prompt: {"summary": "Focused topology.", "missing_relations": ["Input -> Refine"], "reversed_relations": [], "bypassed_relations": [], "invented_relations": [], "repair": ["Connect Input to Refine"], "repair_regions": ["Refine input"], "score": 0.5, "passed": False}
            review = review_candidate(candidate, blueprint, plan, {"template_id": "feedback", "forbidden_copy_terms": []}, mode="vlm", ocr_engine="off", critic_adapter=_passing_critic, topology_adapter=topology)

            self.assertFalse(review["production_pass"])
            self.assertFalse(review["topology"]["passed"])
            self.assertIn("Input -> Refine", review["hard_errors"])
            self.assertIn("Connect Input to Refine", review["repair"])

    def test_issue_free_ten_point_scale_review_is_normalized_by_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate.png"
            blueprint = root / "blueprint.png"
            Image.new("RGB", (1536, 1024), "white").save(candidate)
            Image.new("RGB", (1536, 1024), "white").save(blueprint)
            plan = _plan()
            plan["figure_specification"]["topology"] = "feedback"

            def critic(path, template, prompt):
                result = _passing_critic(path, template, prompt)
                for section in ("ocr", "scientific", "template", "aesthetic"):
                    result[section]["score"] = 7.0
                    result[section]["passed"] = False
                return result

            topology = lambda _path, _prompt: {"summary": "Focused topology.", "missing_relations": [], "reversed_relations": [], "bypassed_relations": [], "invented_relations": [], "repair": [], "repair_regions": [], "score": 10.0, "passed": True}
            review = review_candidate(candidate, blueprint, plan, {"template_id": "feedback", "forbidden_copy_terms": []}, mode="vlm", ocr_engine="off", critic_adapter=critic, topology_adapter=topology)

            self.assertTrue(review["production_pass"])
            self.assertEqual(review["ocr"]["score"], 1.0)
            self.assertEqual(review["scientific"]["score"], 1.0)
            self.assertEqual(review["template"]["score"], 0.7)
            self.assertEqual(review["aesthetic"]["score"], 0.7)

    def test_inspect_pdf_cli_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["inspect-pdf", "--paper", "paper.pdf", "--out", "output/inspect"])
        self.assertEqual(args.command, "inspect-pdf")
        self.assertEqual(args.deadline, 180)
        self.assertEqual(args.ocr_engine, "auto")

    def test_scan_benchmark_cli_accepts_rasterize_dpi(self):
        parser = build_parser()
        args = parser.parse_args(["benchmark", "fast-suite", "--out", "output/scan", "--rasterize-dpi", "144"])
        self.assertEqual(args.rasterize_dpi, 144)

    def test_doctor_reports_easyocr_model_readiness(self):
        report = _doctor()
        models = report["pdf_tools"]["easyocr"]["models"]
        self.assertIn("en_ready", models)
        self.assertIn("en_ch_ready", models)
        self.assertIn("allow_download", models)
        self.assertIn("effective_detector_limit", report["pdf_tools"]["rapidocr"])

    def test_executable_probe_rejects_broken_path_wrapper(self):
        with patch("rfs.cli.shutil.which", return_value=r"C:\broken\pdftoppm.cmd"), patch("rfs.cli.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            run.return_value.stderr = "The system cannot find the path specified."

            result = _probe_executable("pdftoppm")

        self.assertFalse(result["available"])
        self.assertEqual(result["returncode"], 1)
        self.assertIn("cannot find", result["error"])

    def test_fast_framework_prompt_writes_contract_without_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paper = root / "paper.md"
            paper.write_text(PAPER_TEXT, encoding="utf-8")
            out = root / "fast"

            result = run_fast_framework_prompt(
                paper=paper,
                out=out,
                deadline_seconds=180,
                planner_mode="heuristic",
                ocr_engine="off",
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["engineering_only"])
            self.assertFalse(result["production_ready"])
            self.assertEqual(result["deadline_seconds"], 180)
            for name in ["paper.md", "document_model.json", "extraction_report.json", "section_index.json", "section_summary.md", "key_evidence.json", "paper_review.json", "figure_specification.json", "planning_validation_report.json", "image_prompt.md", "overlay_spec.json", "run_report.json"]:
                self.assertTrue((out / name).exists(), name)
            self.assertFalse((out / "selected_image.png").exists())
            overlay = json.loads((out / "overlay_spec.json").read_text(encoding="utf-8"))
            self.assertTrue(overlay["labels"])

    def test_long_scanned_paper_produces_explicit_sampled_engineering_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paper = root / "scan.pdf"
            document = fitz.open()
            for _ in range(12):
                document.new_page(width=600, height=800)
            document.save(paper)
            document.close()

            def adapter(image_path, _lang):
                page_number = int(Path(image_path).stem.rsplit("_", 1)[-1])
                return [{
                    "text": f"Page {page_number} Abstract Method Input Image enters a CNN Backbone and Transformer Encoder Decoder to produce Class Predictions and Bounding Box Predictions with Bipartite Matching.",
                    "confidence": 0.97,
                    "quad": [[20, 20], [920, 20], [920, 100], [20, 100]],
                }]

            out = root / "fast"
            result = run_fast_framework_prompt(
                paper=paper,
                out=out,
                deadline_seconds=180,
                planner_mode="heuristic",
                ocr_engine="easyocr",
                ocr_adapter=adapter,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertFalse(result["production_ready"])
            self.assertEqual(result["extraction_quality"]["semantic_scope"], "sampled_pages_only")
            self.assertTrue(result["extraction_quality"]["sampled_scan_ready"])
            self.assertTrue(any("sample pages" in item for item in result["uncertainties"]))

    def test_production_image_generation_rejects_sampled_scan_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = {
                "ok": True,
                "root": root,
                "paper": str(root / "paper.pdf"),
                "archived_positive": [],
                "archived_negative": [],
                "preferences": {"aspect_ratio": "16:9"},
                "parsed": {"extraction_report": {"scientific_scope_complete": False}},
                "selected_domain": {"id": "general"},
                "paper_review": {},
                "review_metadata": {"mode": "vlm"},
                "plan": _plan(),
                "planner_metadata": {"mode": "vlm"},
                "planning_validation": {"ok": True},
            }
            with patch("rfs.paper_to_image.workflow.prepare_paper_figure_contract", return_value=prepared):
                with self.assertRaisesRegex(RuntimeError, "full-document scientific scope"):
                    run_paper_to_image(paper=root / "paper.pdf", out=root / "run", asset_mode="image2")

    def test_fast_framework_cli_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["fast-framework-prompt", "--paper", "paper.pdf", "--out", "output/fast"])
        self.assertEqual(args.command, "fast-framework-prompt")
        self.assertEqual(args.deadline, 180)
        self.assertEqual(args.planner_mode, "vlm")

    def test_benchmark_fast_cli_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["benchmark", "fast", "--case", "benchmarks/case", "--out", "output/fast"])
        self.assertEqual(args.benchmark_action, "fast")
        self.assertEqual(args.deadline, 180)
        self.assertEqual(args.planner_mode, "vlm")

    def test_benchmark_fast_suite_cli_accepts_repeatable_case_ids(self):
        parser = build_parser()
        args = parser.parse_args(["benchmark", "fast-suite", "--root", "benchmarks", "--out", "output/suite", "--case-id", "101_vit_linear", "--case-id", "106_detr_set_prediction"])
        self.assertEqual(args.benchmark_action, "fast-suite")
        self.assertEqual(args.case_id, ["101_vit_linear", "106_detr_set_prediction"])

    def test_domain_profiles_detect_method_and_survey(self):
        method = {"evidence": [{"text": "A neural model is optimized with a training loss and used during inference."}]}
        survey = {"evidence": [{"text": "This systematic survey presents a taxonomy and review of the landscape."}]}
        self.assertEqual(detect_domain_profile(method)["id"], "ai-ml-method")
        self.assertEqual(detect_domain_profile(survey)["id"], "survey-review")

    def test_strict_review_rejects_ungrounded_relation(self):
        parsed = {"evidence": [{"id": "E0001"}]}
        profile = {"id": "general", "required_sections": ["research_questions", "central_claims", "contributions", "modules", "limitations"]}
        fact = {"id": "f1", "statement": "fact", "status": "required", "evidence_ids": ["E0001"]}
        review = {"research_questions": [fact], "central_claims": [fact], "contributions": [fact], "modules": [{**fact, "id": "m1"}], "limitations": [fact], "research_objects": [], "relations": [{"id": "r1", "source_id": "m1", "target_id": "missing", "evidence_ids": []}], "workflows": {"training": [], "inference": []}, "experiments": {}}
        report = validate_review_coverage(review, parsed, profile, strict=True)
        self.assertFalse(report["ok"])
        self.assertTrue(any("unknown endpoint" in item for item in report["errors"]))

    def test_four_reference_ratios_map_to_expected_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = []
            for name, size in [("arbor", (1831, 979)), ("linear", (1336, 306)), ("tripanel", (804, 277)), ("dense", (2498, 1086))]:
                path = root / f"{name}.png"
                Image.new("RGB", size, "white").save(path)
                refs.append(str(path))
            profiles = build_template_profiles(refs, root / "profiles", mode="heuristic")
            self.assertEqual([item["template_id"] for item in profiles], ["arbor", "linear", "tripanel", "dense-multimodal"])
            selected = select_template(profiles, {"modules": [{"statement": "multimodal retrieval"}] * 10, "inputs": [], "relations": [], "workflows": {"feedback": []}}, requested="auto", target_ratio="auto")
            self.assertEqual(selected["template_id"], "dense-multimodal")
            report = render_layout_blueprint(selected, root / "blueprint.png", "auto")
            self.assertFalse(report["contains_reference_text"])
            self.assertTrue((root / "blueprint.png").exists())

    def test_three_stage_non_loop_workflow_selects_linear_template(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = build_template_profiles([], Path(temp) / "profiles", mode="heuristic")
            review = {
                "modules": [{"statement": value} for value in ("SSL", "RETFound", "supervised learning")],
                "inputs": [{"statement": "CFP"}, {"statement": "OCT"}],
                "relations": [],
                "workflows": {"feedback": []},
            }

            selected = select_template(profiles, review, requested="auto", target_ratio="16:9")

            self.assertEqual(selected["template_id"], "linear")

    def test_feedback_workflow_selects_feedback_template_instead_of_arbor(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = build_template_profiles([], Path(temp) / "profiles", mode="heuristic")
            review = {
                "modules": [{"statement": value} for value in ("Generate", "Initial Output", "Feedback", "Refine", "Refined Output")],
                "inputs": [{"statement": "Input"}],
                "relations": [{"relation_type": "feedback", "statement": "Refined Output returns to Feedback"}],
                "workflows": {"feedback": [{"statement": "iterative self-feedback loop"}]},
            }

            selected = select_template(profiles, review, requested="auto", target_ratio="16:9")

            self.assertEqual(selected["template_id"], "feedback")

    def test_parallel_head_workflow_selects_branch_template(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = build_template_profiles([], Path(temp) / "profiles", mode="heuristic")
            review = {
                "modules": [{"statement": value} for value in ("Backbone", "RPN", "RoIAlign", "classification branch", "box branch", "mask branch")],
                "inputs": [{"statement": "Input Image"}],
                "relations": [{"relation_type": "branch", "statement": "RoIAlign feeds three parallel heads"}],
                "workflows": {"feedback": []},
            }

            selected = select_template(profiles, review, requested="auto", target_ratio="16:9")

            self.assertEqual(selected["template_id"], "branch")

    def test_many_modality_workflow_selects_multimodal_template(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = build_template_profiles([], Path(temp) / "profiles", mode="heuristic")
            review = {
                "inputs": [{"statement": value, "visible_label": value} for value in ("Image", "Text", "Audio", "Depth", "Thermal", "IMU")],
                "modules": [{"statement": "Modality Encoders"}, {"statement": "Joint Embedding Space"}],
                "central_claims": [{"statement": "Cross-modal inputs share one embedding space"}],
                "relations": [],
                "workflows": {"feedback": []},
            }

            selected = select_template(profiles, review, requested="auto", target_ratio="16:9")

            self.assertEqual(selected["template_id"], "multimodal")

    def test_dense_contract_topology_selects_dense_multiframe_template(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = build_template_profiles([], Path(temp) / "profiles", mode="heuristic")
            review = {
                "inputs": [{"statement": "Image"}, {"statement": "Prompt"}],
                "modules": [{"statement": value} for value in ("Image Encoder", "Prompt Encoder", "Mask Decoder")],
                "relations": [],
                "workflows": {"feedback": []},
            }

            selected = select_template(profiles, review, requested="auto", target_ratio="16:9", contract_topology="dense_multiframe")

            self.assertEqual(selected["template_id"], "dense-multiframe")

    @patch("rfs.paper_to_image.generator.requests.post", return_value=FakeResponse())
    def test_mock_image2_generates_three_candidates_and_safe_manifest(self, _post):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-value", "RFS_IMAGE_MODEL": "image-2"}, clear=False):
            root = Path(temp)
            template = {"template_id": "linear", "profile_id": "builtin_linear", "panels": [], "connectors": [], "visual_density": "high", "style": {}, "forbidden_copy_terms": []}
            render_layout_blueprint({**template, "source_aspect_ratio": 1.5}, root / "layout_blueprint.png", "1.5:1")
            result = generate_and_select(_plan(), {"aspect_ratio": "1.5:1", "language": "English"}, template, root / "layout_blueprint.png", root, asset_mode="image2", candidates=3, review_mode="vlm", repair_rounds=1, ocr_engine="vlm", critic_adapter=_passing_critic)
            self.assertTrue(result["selected_passed_all_checks"])
            self.assertEqual(result["successful_candidates"], 3)
            self.assertTrue((root / "selected_image.png").exists())
            manifest_text = (root / "image2_request_manifest.json").read_text(encoding="utf-8")
            manifest = json.loads(manifest_text)
            self.assertEqual(manifest["model"], "gpt-image-2")
            self.assertEqual(len(manifest["requests"]), 3)
            self.assertNotIn("secret-value", manifest_text)
            self.assertTrue(all(item["endpoint"].endswith("/images/edits") for item in manifest["requests"]))
            self.assertEqual(result["stability"]["seed_count"], 3)
            self.assertEqual(result["stability"]["production_pass_rate"], 1.0)
            self.assertEqual(result["stability"]["status"], "stable")
            self.assertTrue((root / "stability_report.json").exists())

    @patch("rfs.paper_to_image.generator.requests.post", side_effect=requests.Timeout("provider stalled"))
    def test_image2_timeout_is_not_blindly_retried(self, post):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-value", "RFS_IMAGE2_TIMEOUT": "30"}, clear=False):
            root = Path(temp)
            template = {"template_id": "linear", "profile_id": "builtin_linear", "panels": [], "connectors": [], "visual_density": "high", "style": {}, "forbidden_copy_terms": []}
            render_layout_blueprint({**template, "source_aspect_ratio": 1.5}, root / "layout_blueprint.png", "1.5:1")

            with self.assertRaises(RuntimeError):
                generate_and_select(
                    _plan(),
                    {"aspect_ratio": "3:2"},
                    template,
                    root / "layout_blueprint.png",
                    root,
                    asset_mode="image2",
                    candidates=1,
                    image_retries=3,
                    review_mode="vlm",
                    repair_rounds=0,
                    ocr_engine="off",
                    critic_adapter=_passing_critic,
                )

            self.assertEqual(post.call_count, 1)

    @patch("rfs.paper_to_image.generator.requests.post")
    def test_three_seed_stability_replaces_only_provider_failed_candidate(self, post):
        calls = {"count": 0}

        def response(*_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise requests.Timeout("provider stalled")
            return FakeResponse()

        post.side_effect = response
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-value", "RFS_STABILITY_REPLACEMENT_RETRIES": "1", "RFS_PAPER_IMAGE_WORKERS": "3"}, clear=False):
            root = Path(temp)
            template = {"template_id": "linear", "profile_id": "builtin_linear", "panels": [], "connectors": [], "visual_density": "high", "style": {}, "forbidden_copy_terms": []}
            render_layout_blueprint({**template, "source_aspect_ratio": 1.5}, root / "layout_blueprint.png", "1.5:1")

            result = generate_and_select(_plan(), {"aspect_ratio": "3:2"}, template, root / "layout_blueprint.png", root, asset_mode="image2", candidates=3, image_retries=1, review_mode="vlm", repair_rounds=0, ocr_engine="off", critic_adapter=_passing_critic)

            self.assertEqual(post.call_count, 4)
            self.assertEqual(result["stability"]["production_pass_rate"], 1.0)
            self.assertEqual(sum("provider_replacement_attempt" in item for item in result["candidates"]), 1)

    @patch("rfs.paper_to_image.generator.requests.post", return_value=FakeResponse())
    def test_resume_candidates_reuses_existing_images_and_generates_only_missing_seed(self, post):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-value", "RFS_PAPER_IMAGE_WORKERS": "3"}, clear=False):
            root = Path(temp)
            template = {"template_id": "linear", "profile_id": "builtin_linear", "panels": [], "connectors": [], "visual_density": "high", "style": {}, "forbidden_copy_terms": []}
            render_layout_blueprint({**template, "source_aspect_ratio": 1.5}, root / "layout_blueprint.png", "1.5:1")
            candidate_dir = root / "candidates"
            candidate_dir.mkdir()
            Image.new("RGB", (1536, 1024), "white").save(candidate_dir / "candidate_01.png")
            Image.new("RGB", (1536, 1024), "white").save(candidate_dir / "candidate_02.png")

            result = generate_and_select(_plan(), {"aspect_ratio": "3:2"}, template, root / "layout_blueprint.png", root, asset_mode="image2", candidates=3, image_retries=1, review_mode="vlm", repair_rounds=0, ocr_engine="off", critic_adapter=_passing_critic, resume_candidates=True)

            self.assertEqual(post.call_count, 1)
            modes = {item["candidate_id"]: item["generation"]["mode"] for item in result["candidates"]}
            self.assertEqual(modes["candidate_01"], "existing_candidate_resume")
            self.assertEqual(modes["candidate_02"], "existing_candidate_resume")
            self.assertEqual(modes["candidate_03"], "edit")
            self.assertEqual(result["stability"]["production_pass_rate"], 1.0)

    @patch("rfs.paper_to_image.generator.requests.post")
    def test_repair_source_skips_fresh_candidate_generation_when_source_passes(self, post):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-value"}, clear=False):
            root = Path(temp)
            blueprint = root / "blueprint.png"
            source = root / "failed_candidate.png"
            Image.new("RGB", (1536, 1024), "white").save(blueprint)
            Image.new("RGB", (1536, 1024), "white").save(source)

            result = generate_and_select(
                _plan(),
                {"aspect_ratio": "3:2", "language": "English"},
                {"template_id": "linear", "forbidden_copy_terms": []},
                blueprint,
                root / "run",
                asset_mode="image2",
                candidates=3,
                review_mode="vlm",
                repair_rounds=1,
                repair_source=source,
                critic_adapter=_passing_critic,
            )

            post.assert_not_called()
            self.assertEqual(result["requested_candidates"], 0)
            self.assertEqual(result["selected_candidate_id"], "source_candidate")
            self.assertTrue(Path(result["selected_image"]).exists())

    @patch("rfs.paper_to_image.generator.requests.post", return_value=FakeResponse())
    def test_failed_candidates_get_one_repair(self, _post):
        calls = {"count": 0}
        def critic(path, blueprint, prompt):
            calls["count"] += 1
            if calls["count"] <= 3:
                result = _passing_critic(path, blueprint, prompt)
                result["ocr"].update({"missing_labels": ["Document Parser"], "score": 0.5, "passed": False})
                result["repair"] = ["Correct the Document Parser label"]
                result["repair_regions"] = ["left panel"]
                result["hard_errors"] = ["missing critical label"]
                return result
            return _passing_critic(path, blueprint, prompt)
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-value", "RFS_IMAGE_MODEL": "image-2"}, clear=False):
            root = Path(temp)
            template = {"template_id": "linear", "profile_id": "builtin_linear", "panels": [], "connectors": [], "visual_density": "high", "style": {}, "forbidden_copy_terms": []}
            render_layout_blueprint({**template, "source_aspect_ratio": 1.5}, root / "layout_blueprint.png", "1.5:1")
            result = generate_and_select(_plan(), {"aspect_ratio": "1.5:1", "language": "English"}, template, root / "layout_blueprint.png", root, asset_mode="image2", candidates=3, review_mode="vlm", repair_rounds=1, ocr_engine="vlm", critic_adapter=critic)
            self.assertEqual(result["repair_candidates"], 1)
            self.assertEqual(result["selected_candidate_id"], "repair_01")
            repair = next(item for item in result["candidates"] if item["candidate_id"] == "repair_01")
            self.assertIn("generation_seconds", repair["timings"])
            self.assertIn("review_seconds", repair["timings"])

    @patch("rfs.paper_to_image.generator.requests.post", return_value=FakeResponse())
    @patch("rfs.paper_to_image.workflow.validate_review_coverage", return_value={"ok": True, "errors": [], "warnings": []})
    @patch("rfs.paper_to_image.planner.call_vlm_json")
    def test_mock_full_production_workflow(self, planner_call, _coverage, _post):
        fact = {"id": "fact_01", "statement": "Evidence-grounded reasoning", "status": "required", "importance": "critical", "confidence": 1.0, "evidence_ids": ["E0001"], "must_appear_in_figure": True, "visual_role": "module"}
        planner_call.return_value = {"summary": "Planning result.", **_plan()}
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "known-test-secret", "RFS_IMAGE_MODEL": "image-2", "RFS_CACHE_DIR": temp}, clear=False):
            root = Path(temp)
            paper = root / "paper.md"
            paper.write_text(PAPER_TEXT, encoding="utf-8")
            out = root / "run"
            result = run_paper_to_image(paper=paper, out=out, planner_mode="vlm", domain_profile="general", template="linear", asset_mode="image2", candidates=3, aspect_ratio="1.5:1", review_mode="vlm", repair_rounds=1, ocr_engine="vlm", critic_adapter=_passing_critic)
            self.assertTrue(result["ok"])
            self.assertEqual(result["paper_review_mode"], "derived_from_vlm_plan")
            self.assertEqual(result["template_id"], "linear")
            self.assertTrue((out / "selected_image.png").exists())
            self.assertFalse(any(out.glob("*.pptx")))
            self.assertEqual(json.loads((out / "image2_request_manifest.json").read_text(encoding="utf-8"))["model"], "gpt-image-2")

    def test_local_ocr_can_block_vlm_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "candidate.png"
            blueprint = root / "blueprint.png"
            Image.new("RGB", (800, 600), "white").save(image)
            Image.new("RGB", (800, 600), "white").save(blueprint)
            review = review_candidate(image, blueprint, _plan(), {"template_id": "linear", "forbidden_copy_terms": []}, mode="vlm", ocr_engine="paddle", ocr_adapter=lambda _p, _l: [{"text": "Evidence Graph Builder"}], critic_adapter=_passing_critic)
            self.assertFalse(review["ocr"]["passed"])
            self.assertIn("Document Parser", review["ocr"]["missing_labels"])
            self.assertFalse(review["production_pass"])


if __name__ == "__main__":
    unittest.main()
