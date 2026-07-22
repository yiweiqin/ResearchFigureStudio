import unittest

from rfs.paper_to_image.planner import validate_plan_grounding
from rfs.paper_to_image.preparation import build_overlay_spec, expand_plan_evidence, normalize_figure_contract


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

    def test_review_fact_ids_expand_to_page_evidence_and_encoder_group(self):
        parsed = {"evidence": [{"id": "E0001", "confidence": 1.0}]}
        review = {"modules": [{"id": "review_encoders", "evidence_ids": ["E0001"]}]}
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "modules": [
                    {"id": "image_encoder", "name": "Image Encoder", "evidence_ids": ["review_encoders"]},
                    {"id": "text_encoder", "name": "Text Encoder", "evidence_ids": ["review_encoders"]},
                    {"id": "audio_encoder", "name": "Audio Encoder", "evidence_ids": ["review_encoders"]},
                    {"id": "joint", "name": "Joint Embedding Space", "evidence_ids": ["E0001"]},
                ],
                "inputs": [{"id": "image", "name": "Image", "evidence_ids": ["E0001"]}],
                "outputs": [],
                "innovations": [],
                "relations": [
                    {"source": "image", "target": "image_encoder", "evidence_ids": ["E0001"]},
                    {"source": "image_encoder", "target": "joint", "evidence_ids": ["E0001"]},
                ],
                "terminology": {},
            },
        }

        expand_plan_evidence(plan, review, parsed)
        spec = normalize_figure_contract(plan, parsed)

        self.assertEqual(plan["figure_specification"]["modules"][0]["evidence_ids"], ["E0001"])
        self.assertTrue(any(item.get("id") == "modality_encoders_group" for item in spec["modules"]))
        self.assertTrue(any(item.get("source") == "image" and item.get("target") == "modality_encoders_group" for item in spec["relations"]))

    def test_contract_completion_adds_required_conditioning_and_output_boundary(self):
        parsed = {"evidence": [{"id": "E0001", "confidence": 1.0}]}
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "modules": [
                    {"id": "patches", "name": "Image Patches", "evidence_ids": ["E0001"]},
                    {"id": "encoder", "name": "Transformer Encoder", "evidence_ids": ["E0001"]},
                    {"id": "head", "name": "MLP Head", "evidence_ids": ["E0001"]},
                ],
                "inputs": [{"id": "image", "name": "Input Image", "evidence_ids": ["E0001"]}],
                "outputs": [{"id": "prediction", "name": "Class Prediction", "evidence_ids": ["E0001"]}],
                "relations": [
                    {"source": "patches", "target": "encoder", "evidence_ids": ["E0001"]},
                    {"source": "encoder", "target": "head", "evidence_ids": ["E0001"]},
                ],
                "must_show": [{"text": "Class Token", "evidence_ids": ["E0001"]}],
                "innovations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        class_token = next(item for item in spec["modules"] if item["name"] == "Class Token")
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}
        self.assertIn(("image", "patches"), pairs)
        self.assertIn((class_token["id"], "encoder"), pairs)
        self.assertIn(("head", "prediction"), pairs)

    def test_overview_caption_and_stage_list_complete_missing_panels(self):
        caption = "Figure 1: Three interconnected components: a promptable segmentation task, a segmentation model (SAM) that powers data annotation, and a data engine for collecting SA-1B, our dataset."
        parsed = {
            "document_index": {"figures": [{"page": 1, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 1, "kind": "caption", "text": caption, "confidence": 1.0},
                {"id": "E0002", "page": 2, "kind": "paragraph", "text": "Our data engine has three stages:", "confidence": 1.0},
                {"id": "E0003", "page": 2, "kind": "paragraph", "text": "assisted-manual, semi-automatic, and fully automatic.", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "modules": [], "inputs": [], "outputs": [], "innovations": [], "relations": [], "must_show": [], "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        labels = {_item["name"] for _item in spec["modules"]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertIn("Promptable segmentation task", labels)
        self.assertIn("Segmentation model (SAM)", labels)
        self.assertIn("Data engine", labels)
        self.assertIn("Assisted-Manual", labels)
        self.assertTrue(any(item.get("name") == "SA-1B" for item in spec["outputs"]))
        self.assertTrue(any("stage_assisted_manual" in source and "stage_semi_automatic" in target for source, target in pairs))


if __name__ == "__main__":
    unittest.main()
