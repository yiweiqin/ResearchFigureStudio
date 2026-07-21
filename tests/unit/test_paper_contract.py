import unittest

from rfs.paper_to_image.planner import validate_plan_grounding
from rfs.paper_to_image.preparation import build_overlay_spec, normalize_figure_contract


class PaperContractTests(unittest.TestCase):
    def _parsed(self):
        return {
            "evidence": [
                {"id": "E0001", "confidence": 1.0},
                {"id": "E0002", "confidence": 0.7, "source": "easyocr"},
            ]
        }

    def test_contract_adds_topology_labels_and_separate_flows(self):
        plan = {
            "paper_summary": {
                "research_problem": {"text": "Understand an input.", "evidence_ids": ["E0001"]},
                "central_claim": {"text": "The method refines its output.", "evidence_ids": ["E0001"]},
                "inputs": [{"id": "input", "name": "Input", "evidence_ids": ["E0001"]}],
                "outputs": [{"id": "output", "name": "Refined Output", "evidence_ids": ["E0001"]}],
                "training_flow": [{"step": "Train", "evidence_ids": ["E0001"]}],
                "inference_flow": [{"step": "Refine", "evidence_ids": ["E0001"]}],
                "unknowns": [],
            },
            "figure_specification": {
                "modules": [{"id": "refiner", "name": "Refiner", "evidence_ids": ["E0001"]}],
                "relations": [{"source": "output", "target": "refiner", "type": "feedback", "evidence_ids": ["E0001"]}],
                "terminology": {"Refiner": "Refiner"},
            },
            "design_plan": {"reading_order": ["input", "refiner", "output"], "groups": []},
        }

        spec = normalize_figure_contract(plan, self._parsed())
        overlay = build_overlay_spec(plan)

        self.assertEqual(spec["topology"], "feedback")
        self.assertEqual(spec["training_flow"][0]["step"], "Train")
        self.assertEqual(spec["inference_flow"][0]["step"], "Refine")
        self.assertIn("Refiner", spec["required_labels"])
        self.assertEqual(overlay["connectors"][0]["source"], "output")
        self.assertTrue(any(item["text"] == "Refined Output" for item in overlay["labels"]))

    def test_grounding_rejects_relation_without_evidence(self):
        plan = {
            "figure_specification": {
                "research_problem": {"text": "Problem", "evidence_ids": ["E0001"]},
                "central_claim": {"text": "Claim", "evidence_ids": ["E0001"]},
                "modules": [
                    {"id": "a", "name": "A", "evidence_ids": ["E0001"]},
                    {"id": "b", "name": "B", "evidence_ids": ["E0001"]},
                ],
                "relations": [{"source": "a", "target": "b", "type": "data_flow", "evidence_ids": []}],
                "inputs": [],
                "outputs": [],
                "innovations": [],
            }
        }

        result = validate_plan_grounding(plan, self._parsed())

        self.assertFalse(result["ok"])
        self.assertIn("relation a -> b has no evidence_ids", result["errors"])

    def test_low_confidence_evidence_is_reported_as_uncertain(self):
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "modules": [{"id": "ocr_module", "name": "OCR Module", "evidence_ids": ["E0002"]}],
                "relations": [],
                "inputs": [],
                "outputs": [],
                "innovations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, self._parsed())

        self.assertIn("ocr_module relies only on low-confidence OCR evidence", spec["uncertainties"])


if __name__ == "__main__":
    unittest.main()
