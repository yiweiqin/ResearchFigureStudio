import tempfile
import unittest
from pathlib import Path

from rfs.semantic_contract import apply_paper_semantic_contract


class SemanticContractTests(unittest.TestCase):
    def test_exact_paper_labels_and_relations_override_image_interpretation(self):
        program = {
            "slots": [
                {"id": "left", "bbox_percent": {"x": 0.05, "y": 0.25, "w": 0.2, "h": 0.3}},
                {"id": "middle", "bbox_percent": {"x": 0.4, "y": 0.25, "w": 0.2, "h": 0.3}},
                {"id": "right", "bbox_percent": {"x": 0.75, "y": 0.25, "w": 0.2, "h": 0.3}},
            ],
            "cards": [],
            "panels": [],
            "arrows": [{"id": "image_guess", "path_percent": [[0.1, 0.1], [0.9, 0.9]]}],
            "text_program": {"items": [{"id": "ocr_wrong", "text": "lnput", "bbox_percent": {"x": 0.08, "y": 0.3, "w": 0.1, "h": 0.04}}]},
        }
        contract = {"figure_specification": {
            "inputs": [{"id": "input", "name": "Exact Input", "evidence_ids": ["E1"]}],
            "modules": [{"id": "method", "name": "Paper Method", "evidence_ids": ["E2"]}],
            "outputs": [{"id": "output", "name": "Exact Output", "evidence_ids": ["E3"]}],
            "innovations": [],
            "relations": [
                {"source": "input", "target": "method", "type": "data_flow", "evidence_ids": ["E4"]},
                {"source": "method", "target": "output", "type": "data_flow", "evidence_ids": ["E5"]},
            ],
        }}
        with tempfile.TemporaryDirectory() as tmp:
            updated, report = apply_paper_semantic_contract(program, contract, Path(tmp))

            labels = {item["text"] for item in updated["text_program"]["items"]}
            self.assertEqual(labels, {"Exact Input", "Paper Method", "Exact Output"})
            self.assertEqual(report["mapped_relation_count"], 2)
            for arrow in updated["arrows"]:
                for start, end in zip(arrow["path_percent"], arrow["path_percent"][1:]):
                    self.assertTrue(start[0] == end[0] or start[1] == end[1], arrow["path_percent"])
            self.assertTrue((Path(tmp) / "semantic_binding_report.json").exists())


if __name__ == "__main__":
    unittest.main()
