import json
import tempfile
import unittest
from pathlib import Path

from rfs.arrow_router import style_and_route_arrows


class ArrowRouterTests(unittest.TestCase):
    def test_reference_paths_are_preserved_and_styled(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            program = {
                "summary": "Figure program.",
                "canvas": {"width_in": 10, "height_in": 5},
                "style": {"color_tokens": [{"token_id": "arrow_001", "hex": "#111111"}]},
                "panels": [],
                "slots": [
                    {"id": "a", "bbox_percent": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}},
                    {"id": "b", "bbox_percent": {"x": 0.4, "y": 0.1, "w": 0.1, "h": 0.1}},
                    {"id": "c", "bbox_percent": {"x": 0.4, "y": 0.3, "w": 0.1, "h": 0.1}},
                ],
                "arrows": [
                    {
                        "id": "flow_a",
                        "source_id": "a",
                        "target_id": "b",
                        "path_percent": [[0.2, 0.15], [0.4, 0.15]],
                        "style_token_id": "arrow_001",
                        "editable_in": "pptx",
                        "render_policy": "ppt_shape_not_image_asset",
                        "binding_source": "reference_control_candidates",
                    },
                    {
                        "id": "flow_b",
                        "source_id": "a",
                        "target_id": "c",
                        "path_percent": [[0.2, 0.15], [0.3, 0.15], [0.3, 0.35], [0.4, 0.35]],
                        "style_token_id": "arrow_001",
                        "editable_in": "pptx",
                        "render_policy": "ppt_shape_not_image_asset",
                        "binding_source": "reference_control_candidates",
                    },
                ],
            }

            result = style_and_route_arrows(program, out, mode="reference")
            by_id = {item["id"]: item for item in result["arrows"]}

            self.assertEqual(by_id["flow_a"]["path_percent"], [[0.2, 0.15], [0.4, 0.15]])
            self.assertTrue(by_id["flow_a"]["reference_locked"])
            self.assertTrue(by_id["flow_a"]["reference_path_preserved"])
            self.assertEqual(by_id["flow_a"]["semantic_role"], "branch")
            self.assertEqual(by_id["flow_a"]["route_style"], "bundled_elbow")
            self.assertEqual(result["style"]["arrow_style_profile_path"], "arrow_style_profile.json")

            quality = json.loads((out / "arrow_quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(quality["summary"], "Arrow routing and styling quality report.")
            self.assertEqual(quality["arrow_count"], 2)
            self.assertFalse(quality["reference_path_overrides"])


if __name__ == "__main__":
    unittest.main()
