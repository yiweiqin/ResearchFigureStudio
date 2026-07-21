import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from rfs.evaluation.benchmarking import (
    list_benchmark_cases,
    score_benchmark_case,
    validate_benchmark_case,
)


ROOT = Path(__file__).resolve().parents[2]


class BenchmarkingTests(unittest.TestCase):
    def test_bundled_cases_validate_and_list(self):
        p2i = ROOT / "benchmarks" / "paper-to-image" / "cases" / "001_linear_pipeline"
        i2p = ROOT / "benchmarks" / "image-to-ppt" / "cases" / "001_three_stage_layout"

        self.assertTrue(validate_benchmark_case(p2i)["ok"])
        self.assertTrue(validate_benchmark_case(i2p)["ok"])
        listing = list_benchmark_cases(ROOT / "benchmarks")
        self.assertGreaterEqual(len(listing["cases"]), 7)

    def test_real_paper_case_is_valid_with_source_metadata(self):
        case_dir = ROOT / "benchmarks" / "paper-to-image" / "cases" / "101_vit_linear"
        validation = validate_benchmark_case(case_dir)

        self.assertTrue(validation["ok"])
        self.assertTrue((case_dir / "source.json").exists())

    def test_paper_to_image_score_uses_hard_scientific_gates(self):
        case_dir = ROOT / "benchmarks" / "paper-to-image" / "cases" / "001_linear_pipeline"
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            review = {
                "scientific": {"score": 1.0, "missing_modules": [], "missing_relations": [], "reversed_relations": [], "invented_items": []},
                "ocr": {"score": 1.0, "missing_labels": [], "misspelled_labels": [], "forbidden_labels_found": []},
                "aesthetic": {"score": 0.9, "readability": 0.9},
                "clarity": {"score": 0.9},
                "information": {"score": 0.95},
                "stability": {"production_pass_rate": 1.0},
                "hard_errors": [],
            }
            (run / "candidate_review.json").write_text(json.dumps({
                "selected_candidate_id": "candidate_01",
                "candidates": [{"candidate_id": "candidate_01", "score": 0.95, "review": review}],
            }), encoding="utf-8")

            result = score_benchmark_case(case_dir, run)

            self.assertTrue(result["passed"])
            self.assertEqual(result["metrics"]["relation_recall"], 1.0)

    def test_paper_to_image_score_checks_planning_contract(self):
        case_dir = ROOT / "benchmarks" / "paper-to-image" / "cases" / "001_linear_pipeline"
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            review = {
                "scientific": {"score": 1.0, "missing_modules": [], "missing_relations": [], "reversed_relations": [], "invented_items": []},
                "ocr": {"score": 1.0, "missing_labels": [], "misspelled_labels": [], "forbidden_labels_found": []},
                "aesthetic": {"score": 0.9, "readability": 0.9},
                "clarity": {"score": 0.9},
                "information": {"score": 0.95},
                "stability": {"production_pass_rate": 1.0},
                "hard_errors": [],
            }
            (run / "candidate_review.json").write_text(json.dumps({
                "selected_candidate_id": "candidate_01",
                "candidates": [{"candidate_id": "candidate_01", "score": 0.95, "review": review}],
            }), encoding="utf-8")
            (run / "figure_specification.json").write_text(json.dumps({
                "modules": [{"id": "only_module", "name": "Feature Encoder"}],
                "relations": [],
            }), encoding="utf-8")

            result = score_benchmark_case(case_dir, run)

            self.assertFalse(result["passed"])
            self.assertLess(result["metrics"]["plan_entity_recall"], 1.0)
            self.assertEqual(result["metrics"]["plan_relation_recall"], 0.0)
            self.assertIn("paper planning missed required benchmark entities", result["hard_failures"])
            self.assertIn("paper planning missed required benchmark relations", result["hard_failures"])

    def test_full_slide_picture_is_detected_as_editability_cheating(self):
        case_dir = ROOT / "benchmarks" / "image-to-ppt" / "cases" / "001_three_stage_layout"
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            reference = case_dir / "reference.ppm"
            with Image.open(reference) as image:
                image.save(run / "rebuild_preview.png")
                image.save(run / "reference.png")
            prs = Presentation()
            prs.slide_width = Inches(10)
            prs.slide_height = Inches(5.625)
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            slide.shapes.add_picture(str(run / "reference.png"), 0, 0, width=prs.slide_width, height=prs.slide_height)
            prs.save(run / "editable_composition.pptx")
            (run / "composition_quality_report.json").write_text(json.dumps({"slots": [], "cards": [], "arrows": []}), encoding="utf-8")
            (run / "rebuild_visual_quality_report.json").write_text(json.dumps({"blocking_issue_count": 0}), encoding="utf-8")

            result = score_benchmark_case(case_dir, run)

            self.assertFalse(result["passed"])
            self.assertEqual(result["metrics"]["full_slide_image_count"], 1)
            self.assertIn("full-slide reference image detected", result["hard_failures"])


if __name__ == "__main__":
    unittest.main()
