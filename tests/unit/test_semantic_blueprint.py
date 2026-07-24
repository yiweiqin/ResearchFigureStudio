import unittest

from rfs.paper_to_image.semantic_blueprint import compile_semantic_blueprint


class SemanticBlueprintTests(unittest.TestCase):
    def test_linear_contract_uses_graph_ranks_and_keeps_parallel_outputs_in_one_layer(self):
        specification = {
            "topology": "linear",
            "required_labels": ["Input", "Embed", "Encoder", "Output A", "Output B"],
            "inputs": [{"id": "input", "name": "Input"}],
            "modules": [{"id": "embed", "name": "Embed"}, {"id": "encoder", "name": "Encoder"}],
            "outputs": [{"id": "a", "name": "Output A"}, {"id": "b", "name": "Output B"}],
            "relations": [
                {"source": "input", "target": "embed", "type": "data_flow"},
                {"source": "embed", "target": "encoder", "type": "data_flow"},
                {"source": "encoder", "target": "a", "type": "data_flow"},
                {"source": "encoder", "target": "b", "type": "data_flow"},
            ],
        }

        report = compile_semantic_blueprint(specification)
        nodes = {item["id"]: item for item in report["nodes"]}

        self.assertTrue(report["applied"])
        self.assertEqual(nodes["input"]["rank"], 0)
        self.assertLess(nodes["embed"]["rank"], nodes["encoder"]["rank"])
        self.assertEqual(nodes["a"]["rank"], nodes["b"]["rank"])
        self.assertNotEqual(nodes["a"]["bbox_percent"]["y"], nodes["b"]["bbox_percent"]["y"])
        output_edges = [item for item in report["connectors"] if item["source"] == "encoder"]
        self.assertNotEqual(output_edges[0]["path_percent"][0][1], output_edges[1]["path_percent"][0][1])

    def test_multimodal_inputs_share_one_layer_and_converge(self):
        specification = {
            "topology": "multimodal",
            "required_labels": ["Image", "Text", "Audio", "Encoders", "Joint Space", "Alignment"],
            "inputs": [{"id": "image", "name": "Image"}, {"id": "text", "name": "Text"}, {"id": "audio", "name": "Audio"}],
            "modules": [{"id": "encoders", "name": "Encoders"}, {"id": "joint", "name": "Joint Space", "role": "shared representation"}],
            "outputs": [{"id": "alignment", "name": "Alignment"}],
            "relations": [
                {"source": "image", "target": "encoders", "type": "encoding"},
                {"source": "text", "target": "encoders", "type": "encoding"},
                {"source": "audio", "target": "encoders", "type": "encoding"},
                {"source": "encoders", "target": "joint", "type": "alignment"},
                {"source": "joint", "target": "alignment", "type": "enables"},
            ],
        }

        report = compile_semantic_blueprint(specification)
        nodes = {item["id"]: item for item in report["nodes"]}

        self.assertTrue(report["applied"])
        self.assertEqual({nodes[node_id]["rank"] for node_id in ("image", "text", "audio")}, {0})
        self.assertEqual(len({nodes[node_id]["bbox_percent"]["x"] for node_id in ("image", "text", "audio")}), 1)
        self.assertGreater(nodes["joint"]["rank"], nodes["encoders"]["rank"])
        input_edges = [item for item in report["connectors"] if item["target"] == "encoders"]
        self.assertEqual(len({item["path_percent"][-1][1] for item in input_edges}), 3)
        self.assertEqual(len({item["path_percent"][1][0] for item in input_edges}), 3)

    def test_feedback_loop_is_routed_outside_the_forward_graph(self):
        specification = {
            "topology": "feedback",
            "required_labels": ["Sample", "Measure", "Update", "Estimate", "repeat"],
            "inputs": [{"id": "sample", "name": "Sample"}],
            "modules": [{"id": "measure", "name": "Measure"}, {"id": "update", "name": "Update"}],
            "outputs": [{"id": "estimate", "name": "Estimate"}],
            "relations": [
                {"source": "sample", "target": "measure", "type": "data_flow"},
                {"source": "measure", "target": "update", "type": "data_flow"},
                {"source": "update", "target": "estimate", "type": "data_flow"},
                {"source": "estimate", "target": "measure", "type": "feedback_loop", "label": "repeat"},
            ],
        }

        report = compile_semantic_blueprint(specification)
        loop = next(item for item in report["connectors"] if item["type"] == "feedback_loop")

        self.assertTrue(report["applied"])
        self.assertEqual(loop["route_style"], "outer_feedback")
        self.assertIn(loop["path_percent"][1][1], {0.05, 0.95})
        self.assertEqual(loop["label"], "repeat")

    def test_source_only_conditioning_nodes_are_placed_immediately_before_their_target(self):
        specification = {
            "topology": "linear",
            "required_labels": ["Input", "Patches", "Projection", "Class Token", "Position Embedding", "Encoder"],
            "inputs": [{"id": "input", "name": "Input"}],
            "modules": [
                {"id": "patches", "name": "Patches"},
                {"id": "projection", "name": "Projection"},
                {"id": "class", "name": "Class Token", "role": "conditioning"},
                {"id": "position", "name": "Position Embedding", "role": "conditioning"},
                {"id": "encoder", "name": "Encoder"},
            ],
            "relations": [
                {"source": "input", "target": "patches", "type": "data_flow"},
                {"source": "patches", "target": "projection", "type": "data_flow"},
                {"source": "projection", "target": "encoder", "type": "data_flow"},
                {"source": "class", "target": "encoder", "type": "conditioning"},
                {"source": "position", "target": "encoder", "type": "conditioning"},
            ],
        }

        report = compile_semantic_blueprint(specification)
        nodes = {item["id"]: item for item in report["nodes"]}

        self.assertEqual(nodes["class"]["rank"], nodes["encoder"]["rank"] - 1)
        self.assertEqual(nodes["position"]["rank"], nodes["encoder"]["rank"] - 1)
        self.assertEqual(nodes["projection"]["rank"], nodes["class"]["rank"])

    def test_required_label_whitelist_excludes_out_of_scope_entities(self):
        specification = {
            "topology": "linear",
            "required_labels": ["Input", "Core", "Output"],
            "inputs": [{"id": "input", "name": "Input"}],
            "modules": [{"id": "core", "name": "Core"}, {"id": "detail", "name": "Out-of-scope Detail"}],
            "outputs": [{"id": "output", "name": "Output"}],
            "innovations": [{"id": "core_innovation", "name": "Core"}],
            "relations": [
                {"source": "input", "target": "core", "type": "data_flow"},
                {"source": "core", "target": "output", "type": "data_flow"},
                {"source": "core", "target": "detail", "type": "data_flow"},
            ],
        }

        report = compile_semantic_blueprint(specification)

        self.assertEqual({item["label"] for item in report["nodes"]}, {"Input", "Core", "Output"})
        self.assertFalse(any(item["target"] == "detail" for item in report["connectors"]))

    def test_skip_layer_relation_uses_bypass_lane_instead_of_crossing_middle_node(self):
        specification = {
            "topology": "branch",
            "required_labels": ["Input", "Middle", "Merge"],
            "inputs": [{"id": "input", "name": "Input"}],
            "modules": [{"id": "middle", "name": "Middle"}, {"id": "merge", "name": "Merge"}],
            "relations": [
                {"source": "input", "target": "middle", "type": "data_flow"},
                {"source": "middle", "target": "merge", "type": "data_flow"},
                {"source": "input", "target": "merge", "type": "conditioning"},
            ],
        }

        report = compile_semantic_blueprint(specification)
        bypass = next(item for item in report["connectors"] if item["source"] == "input" and item["target"] == "merge")

        self.assertEqual(bypass["route_style"], "bypass_orthogonal")
        self.assertGreaterEqual(len(bypass["path_percent"]), 6)

    def test_contract_larger_than_blueprint_limit_is_not_forced_into_one_canvas(self):
        modules = [{"id": f"node_{index}", "name": f"Node {index}"} for index in range(18)]
        specification = {
            "topology": "linear",
            "required_labels": [item["name"] for item in modules],
            "modules": modules,
            "relations": [{"source": f"node_{index}", "target": f"node_{index + 1}", "type": "data_flow"} for index in range(17)],
        }

        report = compile_semantic_blueprint(specification)

        self.assertFalse(report["applied"])
        self.assertEqual(report["reason"], "too_many_nodes")


if __name__ == "__main__":
    unittest.main()
