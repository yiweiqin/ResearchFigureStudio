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

    def test_contract_normalizes_scalar_claim_and_grounds_it_from_evidence(self):
        parsed = {
            "evidence": [
                {
                    "id": "E0001",
                    "page": 3,
                    "text": "The same architecture is used for pre-training and fine-tuning with task-specific output layers.",
                    "confidence": 1.0,
                }
            ]
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": "Unified architecture for pre-training and fine-tuning.",
                "central_claim": "The same architecture is used for pre-training and fine-tuning with task-specific output layers.",
                "modules": [{"id": "encoder", "name": "Encoder", "evidence_ids": ["E0001"]}],
                "inputs": [],
                "outputs": [],
                "innovations": [],
                "relations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        validation = validate_plan_grounding(plan, parsed)

        self.assertEqual(spec["central_claim"]["evidence_ids"], ["E0001"])
        self.assertEqual(spec["research_problem"]["evidence_ids"], ["E0001"])
        self.assertTrue(validation["ok"])

    def test_validation_rejects_cross_script_translation_of_visible_labels(self):
        parsed = {
            "evidence": [
                {"id": "E0001", "text": "输入论文首先进入文档编码器,关系解码器连接实体,最后输出可编辑框架图。", "confidence": 1.0},
            ]
        }
        plan = {
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [{"id": "input", "name": "Input document", "evidence_ids": ["E0001"]}],
                "modules": [{"id": "encoder", "name": "Document encoder", "evidence_ids": ["E0001"]}],
                "outputs": [{"id": "output", "name": "可编辑框架图", "evidence_ids": ["E0001"]}],
                "innovations": [],
                "relations": [
                    {"source": "input", "target": "encoder", "type": "data_flow", "label": "进入", "evidence_ids": ["E0001"]},
                    {"source": "encoder", "target": "output", "type": "prediction", "label": "produces", "evidence_ids": ["E0001"]},
                ],
                "terminology": {},
            }
        }

        validation = validate_plan_grounding(plan, parsed)

        self.assertFalse(validation["ok"])
        self.assertTrue(any("Input document" in item for item in validation["errors"]))
        self.assertTrue(any("Document encoder" in item for item in validation["errors"]))
        self.assertTrue(any("produces" in item for item in validation["errors"]))

    def test_validation_accepts_verbatim_non_english_visible_labels(self):
        parsed = {
            "evidence": [
                {"id": "E0001", "text": "输入论文首先进入文档编码器,关系解码器连接实体,最后输出可编辑框架图。", "confidence": 1.0},
            ]
        }
        plan = {
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [{"id": "input", "name": "输入论文", "evidence_ids": ["E0001"]}],
                "modules": [{"id": "encoder", "name": "文档编码器", "evidence_ids": ["E0001"]}],
                "outputs": [{"id": "output", "name": "可编辑框架图", "evidence_ids": ["E0001"]}],
                "innovations": [],
                "relations": [
                    {"source": "input", "target": "encoder", "type": "data_flow", "label": "进入", "evidence_ids": ["E0001"]},
                    {"source": "encoder", "target": "output", "type": "prediction", "label": "", "evidence_ids": ["E0001"]},
                ],
                "terminology": {"文档编码器": "文档编码器"},
            }
        }

        self.assertTrue(validate_plan_grounding(plan, parsed)["ok"])

    def test_contract_repairs_cross_script_terminology_to_verbatim_source_key(self):
        parsed = {
            "evidence": [
                {"id": "E0001", "text": "输入论文首先进入文档编码器,关系解码器连接实体,最后输出可编辑框架图。", "confidence": 1.0},
            ]
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [{"id": "input", "name": "输入论文", "evidence_ids": ["E0001"]}],
                "modules": [{"id": "encoder", "name": "文档编码器", "evidence_ids": ["E0001"]}],
                "outputs": [{"id": "output", "name": "可编辑框架图", "evidence_ids": ["E0001"]}],
                "innovations": [],
                "relations": [{"source": "input", "target": "encoder", "type": "data_flow", "label": "进入", "evidence_ids": ["E0001"]}],
                "terminology": {"文档编码器": "Document encoder"},
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        self.assertEqual(spec["terminology"]["文档编码器"], "文档编码器")
        self.assertIn("文档编码器", spec["required_labels"])
        self.assertTrue(validate_plan_grounding(plan, parsed)["ok"])

    def test_contract_grounds_exact_innovation_only_from_novelty_evidence(self):
        parsed = {
            "evidence": [
                {"id": "E0001", "text": "本文提出论文编码器和关系解码器,生成可编辑框架图。", "section_hint": "摘要", "confidence": 1.0},
                {"id": "E0002", "text": "A baseline also contains a relation decoder.", "section_hint": "Related Work", "confidence": 1.0},
            ]
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [],
                "modules": [{"id": "decoder", "name": "关系解码器", "evidence_ids": ["E0001"]}],
                "outputs": [],
                "innovations": [{"id": "innovation_decoder", "name": "关系解码器", "evidence_ids": []}],
                "relations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        self.assertEqual(spec["innovations"][0]["evidence_ids"], ["E0001"])
        self.assertTrue(validate_plan_grounding(plan, parsed)["ok"])

    def test_validation_rejects_visible_input_without_evidence(self):
        parsed = {"evidence": [{"id": "E0001", "text": "The encoder produces an output.", "confidence": 1.0}]}
        plan = {
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [{"id": "input", "name": "Input Image", "evidence_ids": []}],
                "modules": [{"id": "encoder", "name": "encoder", "evidence_ids": ["E0001"]}],
                "outputs": [],
                "innovations": [],
                "relations": [],
                "terminology": {},
            }
        }

        validation = validate_plan_grounding(plan, parsed)

        self.assertFalse(validation["ok"])
        self.assertIn("inputs[0] has no evidence_ids", validation["errors"])

    def test_contract_grounds_short_diagram_labels_only_on_overview_figure_page(self):
        parsed = {
            "document_index": {"figures": [{"page": 3, "caption": "Figure 1: Overall pre-training and fine-tuning procedures."}]},
            "evidence": [
                {"id": "E0001", "page": 3, "text": "T 1", "confidence": 1.0},
                {"id": "E0002", "page": 3, "text": "C", "confidence": 1.0},
                {"id": "E0003", "page": 8, "text": "C", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [],
                "modules": [{"id": "encoder", "name": "Encoder", "evidence_ids": ["E0001"]}],
                "outputs": [
                    {"id": "token_output", "name": "T 1", "evidence_ids": []},
                    {"id": "class_output", "name": "C", "evidence_ids": []},
                ],
                "innovations": [],
                "relations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        self.assertEqual(spec["outputs"][0]["evidence_ids"], ["E0001"])
        self.assertEqual(spec["outputs"][1]["evidence_ids"], ["E0002"])
        self.assertTrue(validate_plan_grounding(plan, parsed)["ok"])

    def test_contract_grounds_declared_multword_entity_by_exact_paper_term(self):
        parsed = {
            "page_count": 6,
            "evidence": [
                {"id": "E0001", "page": 6, "text": "Transformer encoder. First, a convolution reduces the channel dimension.", "confidence": 0.98},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "modules": [{"id": "encoder", "name": "Transformer Encoder", "evidence_ids": []}],
                "inputs": [],
                "outputs": [],
                "innovations": [],
                "relations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        self.assertEqual(spec["modules"][0]["evidence_ids"], ["E0001"])
        self.assertIn("encoder", plan["contract_completion_report"]["grounded_entities"])

    def test_contract_does_not_add_cross_modal_edges_to_connected_inputs(self):
        parsed = {"evidence": [{"id": "E0001", "page": 1, "text": "图像进入图像编码器，论文文本进入文本编码器。", "confidence": 1.0}]}
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [
                    {"id": "image", "name": "图像", "evidence_ids": ["E0001"]},
                    {"id": "text", "name": "论文文本", "evidence_ids": ["E0001"]},
                ],
                "modules": [
                    {"id": "image_encoder", "name": "图像编码器", "evidence_ids": ["E0001"]},
                    {"id": "text_encoder", "name": "文本编码器", "evidence_ids": ["E0001"]},
                ],
                "outputs": [],
                "innovations": [],
                "relations": [
                    {"source": "image", "target": "image_encoder", "evidence_ids": ["E0001"]},
                    {"source": "text", "target": "text_encoder", "evidence_ids": ["E0001"]},
                ],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertEqual(pairs, {("image", "image_encoder"), ("text", "text_encoder")})

    def test_contract_leaves_unknown_input_unconnected_instead_of_guessing(self):
        parsed = {"evidence": [{"id": "E0001", "page": 1, "text": "A scientific system contains two modules.", "confidence": 1.0}]}
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [{"id": "signal", "name": "Scientific Signal", "evidence_ids": ["E0001"]}],
                "modules": [
                    {"id": "first", "name": "First Module", "evidence_ids": ["E0001"]},
                    {"id": "second", "name": "Second Module", "evidence_ids": ["E0001"]},
                ],
                "outputs": [],
                "innovations": [],
                "relations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        self.assertFalse(any(item["source"] == "signal" for item in spec["relations"]))

    def test_contract_normalizes_string_entities_and_relation_alias_fields(self):
        parsed = {
            "evidence": [
                {"id": "E0001", "page": 1, "text": "The Image Encoder sends representations to the Mask Decoder.", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {
                "unknowns": [],
                "core_modules": ["Image Encoder", "Mask Decoder"],
            },
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [],
                "modules": [],
                "outputs": [],
                "innovations": [],
                "relations": [
                    {"source_id": "Image Encoder", "target_id": "Mask Decoder", "relation_type": "feature_flow", "evidence_ids": ["E0001"]},
                ],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        validation = validate_plan_grounding(plan, parsed)

        self.assertEqual([item["name"] for item in spec["modules"]], ["Image Encoder", "Mask Decoder"])
        self.assertEqual(spec["relations"][0]["source"], spec["modules"][0]["id"])
        self.assertEqual(spec["relations"][0]["target"], spec["modules"][1]["id"])
        self.assertEqual(spec["relations"][0]["type"], "feature_flow")
        self.assertTrue(validation["ok"])

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

    def test_generic_completion_recovers_detr_without_bibliography_noise(self):
        captions = [
            "Fig. 1: DETR directly predicts the final set of detections by combining a common CNN with a transformer architecture. During training, bipartite matching uniquely assigns predictions with ground truth boxes and class predictions.",
            "Fig. 2: DETR uses a conventional CNN backbone for an input image, supplements features with a positional encoding, passes them into a transformer encoder, and uses object queries in a transformer decoder. A feed forward network predicts a class and bounding box.",
        ]
        parsed = {
            "page_count": 12,
            "document_index": {"figures": [{"page": index + 1, "caption": text} for index, text in enumerate(captions)]},
            "evidence": [
                {"id": f"E000{index + 1}", "page": index + 1, "kind": "caption", "text": text, "confidence": 1.0}
                for index, text in enumerate(captions)
            ] + [{"id": "E0099", "page": 11, "kind": "heading", "text": "Learning non-maximum suppression. In: ECCV", "section_hint": "References", "confidence": 1.0}],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        labels = {_item.get("name") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}

        self.assertIn("Object Queries", labels)
        self.assertIn("Bipartite Matching", labels)
        self.assertIn("Bounding Box Predictions", labels)
        self.assertNotIn("Non-Maximum Suppression", labels)
        self.assertIn((ids["Object Queries"], ids["Transformer Decoder"]), pairs)
        self.assertIn((ids["Feed Forward Network"], ids["Bounding Box Predictions"]), pairs)

    def test_generic_completion_keeps_clip_modalities_and_encoders_distinct(self):
        caption = "Figure 1. Summary of our approach. CLIP jointly trains an image encoder and a text encoder to predict the correct pairings of a batch of (image, text) training examples. At test time the text encoder synthesizes a zero-shot linear classifier by embedding the names or descriptions of the target classes."
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 3, "kind": "paragraph", "text": "The image encoder and text encoder maximize similarity of image and text embeddings using a contrastive objective.", "section_hint": "Method", "confidence": 1.0},
            ],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [{"id": "fallback_contrastive", "name": "Contrastive Pre-training", "role": "paper-derived stage requiring VLM verification", "evidence_ids": ["E0002"]}], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertNotEqual(ids["Text"], ids["Text Encoder"])
        self.assertIn((ids["Text"], ids["Text Encoder"]), pairs)
        self.assertIn((ids["Class Descriptions"], ids["Text Encoder"]), pairs)
        self.assertIn((ids["Text Encoder"], ids["Text Embeddings"]), pairs)
        self.assertTrue(any(item.get("id") == "fallback_contrastive" for item in spec["modules"]))
        self.assertEqual(spec["topology"], "multimodal")

    def test_rich_clip_contract_reuses_singular_embedding_entities(self):
        caption = "Figure 1. CLIP trains an image encoder and a text encoder on paired image and text inputs, then embeds class descriptions for a zero-shot classifier."
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 3, "kind": "paragraph", "text": "The image and text embeddings are aligned by a contrastive objective.", "section_hint": "Method", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "inputs": [
                    {"id": "images", "name": "Image", "evidence_ids": ["E0001"]},
                    {"id": "texts", "name": "Text", "evidence_ids": ["E0001"]},
                    {"id": "classes", "name": "Class Descriptions", "evidence_ids": ["E0001"]},
                ],
                "modules": [
                    {"id": "image_encoder", "name": "Image Encoder", "evidence_ids": ["E0001"]},
                    {"id": "text_encoder", "name": "Text Encoder", "evidence_ids": ["E0001"]},
                    {"id": "contrastive", "name": "Contrastive Learning", "evidence_ids": ["E0002"]},
                ],
                "outputs": [
                    {"id": "image_embedding", "name": "image embedding", "evidence_ids": ["E0002"]},
                    {"id": "text_embedding", "name": "text embedding", "evidence_ids": ["E0002"]},
                    {"id": "classifier", "name": "Zero-Shot Classifier", "evidence_ids": ["E0001"]},
                ],
                "relations": [{"source": "image_embedding", "target": "classifier", "type": "classification", "evidence_ids": ["E0001", "E0002"]}],
                "innovations": [],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        embedding_labels = [
            item.get("name")
            for field in ("inputs", "modules", "outputs")
            for item in spec[field]
            if "embedding" in str(item.get("name") or "").casefold()
        ]
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertEqual(len([label for label in embedding_labels if "image" in label.casefold()]), 1)
        self.assertEqual(len([label for label in embedding_labels if "text" in label.casefold()]), 1)
        self.assertIn(("text_embedding", "classifier"), pairs)

    def test_rich_bert_contract_uses_selected_caption_for_context_rules(self):
        caption = "Figure 2: BERT input representation. The input embeddings are the sum of the token embeddings, the segmentation embeddings and the position embeddings."
        parsed = {
            "page_count": 12,
            "document_index": {"figures": [{"page": 5, "caption": caption}]},
            "evidence": [{"id": "E0001", "page": 5, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0}],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "inputs": [{"id": "tokens", "name": "Input Sequence", "evidence_ids": ["E0001"]}],
                "modules": [
                    {"id": "token_embeddings", "name": "Token Embeddings", "evidence_ids": ["E0001"]},
                    {"id": "position_embeddings", "name": "Position Embeddings", "evidence_ids": ["E0001"]},
                    {"id": "bert", "name": "Bidirectional Transformer Encoder", "evidence_ids": ["E0001"]},
                ],
                "outputs": [],
                "innovations": [],
                "relations": [{"source": "tokens", "target": "token_embeddings", "type": "embedding", "evidence_ids": ["E0001"]}],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        ids = {item.get("name"): item.get("id") for field in ("inputs", "modules", "outputs") for item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertIn("Segment Embeddings", ids)
        self.assertIn("Input Representation", ids)
        self.assertIn((ids["Segment Embeddings"], ids["Input Representation"]), pairs)

    def test_rich_nerf_contract_reuses_parenthesized_mlp_and_recovers_distant_method_step(self):
        overview = "Figure 2: A neural radiance field samples 5D coordinates along camera rays and uses an MLP to predict color and volume density for volume rendering."
        encoding = "We transform each sampled 3D point with a positional encoding before passing it into the MLP."
        parsed = {
            "page_count": 10,
            "document_index": {"figures": [{"page": 2, "caption": overview}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": overview, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 6, "kind": "paragraph", "text": encoding, "section_hint": "Method", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "inputs": [{"id": "ray", "name": "Camera Rays", "evidence_ids": ["E0001"]}],
                "modules": [
                    {"id": "points", "name": "Sampled 3D Points", "evidence_ids": ["E0001", "E0002"]},
                    {"id": "field", "name": "MLP (F_theta)", "evidence_ids": ["E0001", "E0002"]},
                    {"id": "render", "name": "Volume Rendering", "evidence_ids": ["E0001"]},
                ],
                "outputs": [{"id": "image", "name": "Rendered Image", "evidence_ids": ["E0001"]}],
                "innovations": [],
                "relations": [{"source": "ray", "target": "points", "type": "sampling", "evidence_ids": ["E0001"]}],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        mlps = [item for item in spec["modules"] if str(item.get("name") or "").casefold().startswith("mlp")]
        positional = next(item for item in spec["modules"] if item.get("name") == "Positional Encoding")
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertEqual(len(mlps), 1)
        self.assertIn(("points", positional["id"]), pairs)
        self.assertIn((positional["id"], "field"), pairs)

    def test_rich_transformer_contract_recovers_connected_steps_from_distant_method_evidence(self):
        caption = "Figure 1: The Transformer follows an encoder-decoder architecture."
        method = "We use learned embeddings to convert the input tokens and output tokens to vectors. Output embeddings are offset by one position. A linear transformation and softmax convert the decoder output to predicted next-token probabilities."
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 6, "kind": "paragraph", "text": method, "section_hint": "Method", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "inputs": [
                    {"id": "input_embedding", "name": "Input Embedding", "evidence_ids": ["E0002"]},
                    {"id": "output_embedding", "name": "Output Embedding", "evidence_ids": ["E0002"]},
                    {"id": "target_sequence", "name": "output sequence", "evidence_ids": ["E0002"]},
                ],
                "modules": [
                    {"id": "encoder", "name": "Encoder Stack", "evidence_ids": ["E0001"]},
                    {"id": "decoder", "name": "Decoder Stack", "evidence_ids": ["E0001"]},
                    {"id": "softmax", "name": "Softmax", "evidence_ids": ["E0002"]},
                ],
                "outputs": [],
                "innovations": [],
                "relations": [{"source": "encoder", "target": "decoder", "type": "cross_attention", "evidence_ids": ["E0001"]}],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        ids = {item.get("name"): item.get("id") for field in ("inputs", "modules", "outputs") for item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertIn((ids["Inputs"], "input_embedding"), pairs)
        self.assertEqual(ids["Outputs (shifted right)"], "target_sequence")
        self.assertIn(("target_sequence", "output_embedding"), pairs)
        self.assertIn(("softmax", ids["Output Probabilities"]), pairs)

    def test_generic_completion_recovers_nerf_branch_without_false_multimodal_topology(self):
        caption = "Fig. 2: An overview of our neural radiance field and differentiable rendering procedure. We synthesize images by sampling 5D coordinates along camera rays, feeding locations and viewing direction into an MLP to produce a color and volume density, and using volume rendering to composite these values into an image."
        positional = "Fig. 4: Our full model passes input coordinates through a high-frequency positional encoding."
        parsed = {
            "page_count": 10,
            "document_index": {"figures": [{"page": 2, "caption": caption}, {"page": 4, "caption": positional}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Method", "confidence": 1.0},
                {"id": "E0002", "page": 4, "kind": "caption", "text": positional, "section_hint": "Method", "confidence": 1.0},
            ],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertIn((ids["Viewing Direction"], ids["MLP"]), pairs)
        self.assertIn((ids["MLP"], ids["Color"]), pairs)
        self.assertIn((ids["Volume Rendering"], ids["Rendered Image"]), pairs)
        self.assertEqual(spec["topology"], "branch")

    def test_generic_completion_recovers_encoder_decoder_from_method_lines(self):
        caption = "Figure 1: The model architecture."
        lines = [
            "Here, the encoder maps an input sequence of symbol representations to continuous representations.",
            "The encoder is composed of a stack of identical layers.",
            "The decoder is also composed of a stack of identical layers and attends over the output of the encoder stack.",
            "We use learned embeddings to convert the input",
            "tokens and output tokens to vectors. We also use the usual learned linear transfor-",
            "mation and softmax function to convert the decoder output to predicted next-token probabilities.",
            "The output embeddings are offset by one position.",
            "We add positional encodings to the input embeddings at the bottoms of the encoder and decoder stacks.",
        ]
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [{"id": "E0001", "page": 2, "kind": "caption", "text": caption, "confidence": 1.0}]
            + [{"id": f"E00{index + 2:02d}", "page": 3 + index // 3, "kind": "paragraph", "text": text, "section_hint": "Method", "confidence": 1.0} for index, text in enumerate(lines)],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        for label in ("Inputs", "Input Embedding", "Encoder Stack", "Outputs (shifted right)", "Output Embedding", "Decoder Stack", "Linear", "Softmax", "Output Probabilities"):
            self.assertIn(label, ids)
        self.assertIn((ids["Encoder Stack"], ids["Decoder Stack"]), pairs)
        self.assertIn((ids["Linear"], ids["Softmax"]), pairs)

    def test_generic_completion_treats_refinement_action_as_refined_output(self):
        caption = "Figure 1: Given an input, the system starts by generating an output, gets feedback, and then refines the previously generated output."
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [{"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0}],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        self.assertIn("Refine", ids)
        self.assertIn("Refined Output", ids)
        self.assertIn((ids["Refine"], ids["Refined Output"]), pairs)

    def test_generic_completion_recovers_embedding_pretraining_and_finetuning(self):
        captions = [
            "Figure 1: Overall pre-training and fine-tuning procedures. The same pre-trained model parameters are used to initialize models for different down-stream tasks.",
            "Figure 2: Input representation. The input embeddings are the sum of the token embeddings, the segmentation embeddings and the position embeddings.",
        ]
        method = [
            "The model architecture is a multi-layer bidirectional Transformer encoder.",
            "Task #1: Masked LM",
            "Task #2: Next Sentence Prediction (NSP)",
            "We represent the input sequence and fine-tune using labeled data from the downstream tasks.",
        ]
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": index + 2, "caption": text} for index, text in enumerate(captions)]},
            "evidence": [{"id": f"E000{index + 1}", "page": index + 2, "kind": "caption", "text": text, "section_hint": "Figure Captions", "confidence": 1.0} for index, text in enumerate(captions)]
            + [{"id": f"E001{index}", "page": 4, "kind": "paragraph", "text": text, "section_hint": "Method", "confidence": 1.0} for index, text in enumerate(method)],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        for label in ("Input Sequence", "Token Embeddings", "Segment Embeddings", "Position Embeddings", "Input Representation", "Bidirectional Transformer Encoder", "Masked LM", "Next Sentence Prediction", "Fine-tuning", "Downstream Tasks"):
            self.assertIn(label, ids)
        self.assertIn((ids["Token Embeddings"], ids["Input Representation"]), pairs)
        self.assertIn((ids["Bidirectional Transformer Encoder"], ids["Fine-tuning"]), pairs)

    def test_generic_completion_recovers_elided_embedding_list_across_ocr_blocks(self):
        caption = "Figure 1: Overall pre-training and fine-tuning procedures."
        parsed = {
            "page_count": 16,
            "document_index": {"figures": [{"page": 3, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 3, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 0.99},
                {"id": "E0002", "page": 4, "kind": "paragraph", "text": "For a given token, its input representation is", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0003", "page": 4, "kind": "paragraph", "text": "constructed by summing the corresponding token,", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0004", "page": 4, "kind": "paragraph", "text": "segment, and position embeddings.", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0005", "page": 4, "kind": "paragraph", "text": "The architecture is a multi-layer bidirectional Transformer encoder.", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0006", "page": 4, "kind": "paragraph", "text": "We pre-train with Masked LM and Next Sentence Prediction before fine-tuning on downstream tasks.", "section_hint": "Method", "confidence": 0.98},
            ],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        for label in ("Input Sequence", "Token Embeddings", "Segment Embeddings", "Position Embeddings", "Input Representation", "Bidirectional Transformer Encoder"):
            self.assertIn(label, ids)
        self.assertIn((ids["Token Embeddings"], ids["Input Representation"]), pairs)
        self.assertIn((ids["Segment Embeddings"], ids["Input Representation"]), pairs)
        self.assertIn((ids["Position Embeddings"], ids["Input Representation"]), pairs)

    def test_generic_completion_uses_selected_architecture_page_context_and_diagram_labels(self):
        captions = [
            "Figure 1: Direct set prediction combines a CNN with a transformer and bipartite matching.",
            "Figure 10: Architecture of the proposed transformer's subsystem. See the detailed description on this page.",
        ]
        parsed = {
            "page_count": 24,
            "document_index": {"figures": [{"page": 2, "caption": captions[0]}, {"page": 20, "caption": captions[1]}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "bbox": [40, 300, 500, 320], "text": captions[0], "section_hint": "Figure Captions", "confidence": 0.98},
                {"id": "E0002", "page": 4, "kind": "paragraph", "bbox": [40, 220, 500, 240], "text": "The input image is processed for direct prediction with bipartite matching.", "section_hint": "Object Detection Method", "confidence": 0.98},
                {"id": "E0003", "page": 20, "kind": "caption", "bbox": [40, 600, 500, 620], "text": captions[1], "section_hint": "Figure Captions", "confidence": 0.98},
                {"id": "E0004", "page": 20, "kind": "paragraph", "bbox": [40, 100, 500, 120], "text": "Image features from the CNN backbone are passed through the transformer encoder.", "section_hint": "Detailed Architecture", "confidence": 0.98},
                {"id": "E0005", "page": 20, "kind": "paragraph", "bbox": [40, 150, 500, 170], "text": "The decoder receives object queries and encoder memory.", "section_hint": "Detailed Architecture", "confidence": 0.98},
                {"id": "E0006", "page": 20, "kind": "paragraph", "bbox": [340, 280, 380, 300], "text": "FFN", "section_hint": "Detailed Architecture", "confidence": 0.98},
                {"id": "E0007", "page": 20, "kind": "paragraph", "bbox": [140, 390, 190, 410], "text": "Encoder", "section_hint": "Detailed Architecture", "confidence": 0.98},
                {"id": "E0008", "page": 20, "kind": "paragraph", "bbox": [310, 310, 360, 330], "text": "Add & Norm", "section_hint": "Detailed Architecture", "confidence": 0.98},
                {"id": "E0009", "page": 20, "kind": "paragraph", "bbox": [40, 180, 500, 200], "text": "The final class labels and bounding boxes are predicted in parallel.", "section_hint": "Detailed Architecture", "confidence": 0.98},
                {"id": "E0010", "page": 20, "kind": "paragraph", "bbox": [40, 710, 500, 730], "text": "For example, a separate text encoder uses class descriptions and contrastive learning to create text embeddings.", "section_hint": "Related Work", "confidence": 0.98},
            ],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        for label in ("Input Image", "CNN Backbone", "Transformer Encoder", "Object Queries", "Transformer Decoder", "Feed Forward Network", "Class Predictions", "Bounding Box Predictions", "Bipartite Matching"):
            self.assertIn(label, ids)
        self.assertIn((ids["CNN Backbone"], ids["Transformer Encoder"]), pairs)
        self.assertIn((ids["Object Queries"], ids["Transformer Decoder"]), pairs)
        self.assertIn((ids["Feed Forward Network"], ids["Class Predictions"]), pairs)
        self.assertNotIn("Text Encoder", ids)
        self.assertNotIn("Contrastive Learning", ids)

    def test_generic_completion_recovers_retrieval_conditioned_generation(self):
        caption = "Figure 1: Overview of our approach. We combine a pre-trained retriever (Query Encoder + Document Index) with a pre-trained seq2seq model (Generator). For query x, we use MIPS to find the top-K documents. For final prediction y, the generator produces the output sequence."
        result_caption = "Figure 2: Posterior for each generated token with five retrieved documents."
        parsed = {
            "page_count": 6,
            "document_index": {"figures": [{"page": 2, "caption": caption}, {"page": 5, "caption": result_caption}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 5, "kind": "caption", "text": result_caption, "section_hint": "Figure Captions", "confidence": 1.0},
            ],
        }
        plan = {"paper_summary": {"unknowns": []}, "figure_specification": {"modules": [], "inputs": [], "outputs": [], "relations": [], "innovations": [], "must_show": [], "terminology": {}}}

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        for label in ("Input Query", "Query Encoder", "Document Index", "Retriever", "Top-K Documents", "Generator", "Output Sequence"):
            self.assertIn(label, ids)
        self.assertNotIn("Generate", ids)
        self.assertIn((ids["Document Index"], ids["Retriever"]), pairs)
        self.assertIn((ids["Top-K Documents"], ids["Generator"]), pairs)

    def test_rag_contract_repairs_latent_endpoint_alias_and_acronym_evidence(self):
        caption = "Figure 1: Overview of our approach. Query Encoder and Document Index use Maximum Inner Product Search (MIPS) to find the top-K documents z. The Generator conditions on those latent documents."
        parsed = {
            "page_count": 4,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [{"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0}],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [],
                "modules": [
                    {"id": "query_encoder", "name": "Query Encoder", "evidence_ids": ["E0001"]},
                    {"id": "doc_index", "name": "Document Index", "evidence_ids": ["E0001"]},
                    {"id": "generator", "name": "Generator", "evidence_ids": ["E0001"]},
                    {"id": "mips", "name": "MIPS", "evidence_ids": []},
                ],
                "outputs": [],
                "innovations": [],
                "relations": [
                    {"source": "mips", "target": "latent_z", "type": "branch", "label": "Top-K Documents", "evidence_ids": []},
                    {"source": "latent_z", "target": "generator", "type": "conditioning", "label": "context", "evidence_ids": []},
                ],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        validation = validate_plan_grounding(plan, parsed)
        ids = {item["name"]: item["id"] for item in spec["modules"]}
        pairs = {(item["source"], item["target"]): item for item in spec["relations"]}

        self.assertTrue(next(item for item in spec["modules"] if item["name"] == "MIPS")["evidence_ids"])
        self.assertIn(("mips", ids["Top-K Documents"]), pairs)
        self.assertIn((ids["Top-K Documents"], "generator"), pairs)
        self.assertTrue(pairs[("mips", ids["Top-K Documents"])]["evidence_ids"])
        self.assertFalse(any("latent_z" in (item["source"], item["target"]) for item in spec["relations"]))
        self.assertTrue(validation["ok"])

    def test_rich_sam_contract_does_not_import_unrelated_clip_components(self):
        sam_caption = "Figure 1: The promptable segmentation model contains an image encoder, prompt encoder, and mask decoder that produces a valid segmentation mask."
        parsed = {
            "page_count": 8,
            "document_index": {"figures": [{"page": 2, "caption": sam_caption}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": sam_caption, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 1, "kind": "paragraph", "text": "CLIP uses class descriptions, a text encoder, text embeddings, and contrastive learning.", "section_hint": "Introduction", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "research_problem": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "central_claim": {"text": "unknown", "evidence_ids": [], "status": "unknown"},
                "inputs": [{"id": "image", "name": "Image", "evidence_ids": ["E0001"]}],
                "modules": [
                    {"id": "image_encoder", "name": "Image Encoder", "evidence_ids": ["E0001"]},
                    {"id": "prompt_encoder", "name": "Prompt Encoder", "evidence_ids": ["E0001"]},
                    {"id": "mask_decoder", "name": "Mask Decoder", "evidence_ids": ["E0001"]},
                ],
                "outputs": [{"id": "mask", "name": "Valid Segmentation Mask", "evidence_ids": ["E0001"]}],
                "innovations": [],
                "relations": [
                    {"source": "image", "target": "image_encoder", "type": "data_flow", "evidence_ids": ["E0001"]},
                    {"source": "image_encoder", "target": "mask_decoder", "type": "feature_flow", "evidence_ids": ["E0001"]},
                    {"source": "prompt_encoder", "target": "mask_decoder", "type": "conditioning", "evidence_ids": ["E0001"]},
                    {"source": "mask_decoder", "target": "mask", "type": "prediction", "evidence_ids": ["E0001"]},
                ],
                "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        labels = {_item.get("name") for field in ("inputs", "modules", "outputs") for _item in spec[field]}

        self.assertNotIn("Class Descriptions", labels)
        self.assertNotIn("Text Encoder", labels)
        self.assertNotIn("Contrastive Learning", labels)
        self.assertTrue(plan["contract_completion_report"]["conservative_expansion"])

    def test_generic_completion_repairs_vlm_ids_labels_and_relation_grounding(self):
        caption = "Figure 1: Pre-training and fine-tuning procedures."
        parsed = {
            "page_count": 5,
            "document_index": {"figures": [{"page": 2, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 2, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 1.0},
                {"id": "E0002", "page": 3, "kind": "paragraph", "text": "The input embeddings are the sum of the token embeddings, segmentation embeddings and position embeddings.", "section_hint": "Method", "confidence": 1.0},
                {"id": "E0003", "page": 3, "kind": "paragraph", "text": "The architecture is a multi-layer bidirectional Transformer encoder.", "section_hint": "Method", "confidence": 1.0},
                {"id": "E0004", "page": 4, "kind": "paragraph", "text": "We train with a masked language model and next sentence prediction.", "section_hint": "Method", "confidence": 1.0},
                {"id": "E0005", "page": 4, "kind": "paragraph", "text": "We represent the input sequence for downstream tasks.", "section_hint": "Method", "confidence": 1.0},
                {"id": "E0006", "page": 1, "kind": "paragraph", "text": "A major limitation is that standard language models are", "section_hint": "Introduction", "confidence": 1.0},
                {"id": "E0007", "page": 1, "kind": "paragraph", "text": "unidirectional.", "section_hint": "Introduction", "confidence": 1.0},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "inputs": [{"id": "input_tokens", "name": "input example", "evidence_ids": ["E0005"]}],
                "modules": [
                    {"id": "embedding_layer", "name": "input embeddings", "evidence_ids": ["E0002"]},
                    {"id": "transformer_encoder", "name": "Bidirectional Transformer Encoder", "evidence_ids": ["E0003"]},
                    {"id": "mlm_head", "name": "MLM objective", "evidence_ids": []},
                ],
                "research_problem": {"text": "Standard language models are unidirectional.", "evidence_ids": []},
                "outputs": [], "innovations": [], "must_show": [], "terminology": {},
                "relations": [
                    {"source": "embedding_layer", "target": "transformer_encoder", "type": "data_flow", "evidence_ids": []},
                    {"source": "transformer_encoder", "target": "mlm_head", "type": "prediction", "evidence_ids": []},
                ],
            },
        }

        spec = normalize_figure_contract(plan, parsed)

        self.assertEqual(next(item for item in spec["inputs"] if item["id"] == "input_tokens")["name"], "Input Sequence")
        self.assertEqual(next(item for item in spec["modules"] if item["id"] == "mlm_head")["name"], "Masked LM")
        self.assertTrue(next(item for item in spec["modules"] if item["id"] == "mlm_head")["evidence_ids"])
        self.assertTrue(all(item.get("evidence_ids") for item in spec["relations"] if item.get("source") in {"embedding_layer", "transformer_encoder"} and item.get("target") in {"transformer_encoder", "mlm_head"}))
        self.assertEqual(spec["research_problem"]["evidence_ids"], ["E0006", "E0007"])

    def test_rich_contract_expands_newly_grounded_intermediate_to_evidence_neighbors(self):
        caption = "Figure 1: Overall pre-training and fine-tuning procedures."
        parsed = {
            "page_count": 16,
            "document_index": {"figures": [{"page": 3, "caption": caption}]},
            "evidence": [
                {"id": "E0001", "page": 3, "kind": "caption", "text": caption, "section_hint": "Figure Captions", "confidence": 0.99},
                {"id": "E0002", "page": 4, "kind": "paragraph", "text": "For a given token, its input representation is", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0003", "page": 4, "kind": "paragraph", "text": "constructed by summing the corresponding token,", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0004", "page": 4, "kind": "paragraph", "text": "segment, and position embeddings.", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0005", "page": 4, "kind": "paragraph", "text": "The architecture is a multi-layer bidirectional Transformer encoder.", "section_hint": "Method", "confidence": 0.98},
                {"id": "E0006", "page": 4, "kind": "paragraph", "text": "We train with Masked LM and Next Sentence Prediction before fine-tuning on downstream tasks.", "section_hint": "Method", "confidence": 0.98},
            ],
        }
        plan = {
            "paper_summary": {"unknowns": []},
            "figure_specification": {
                "inputs": [{"id": "sentence_pair", "name": "Sentence Pair", "evidence_ids": ["E0001"]}],
                "modules": [
                    {"id": "bert", "name": "Bidirectional Transformer Encoder", "evidence_ids": ["E0005"]},
                    {"id": "mlm", "name": "Masked LM", "evidence_ids": ["E0006"]},
                    {"id": "nsp", "name": "Next Sentence Prediction", "evidence_ids": ["E0006"]},
                ],
                "outputs": [{"id": "tasks", "name": "Downstream Tasks", "evidence_ids": ["E0006"]}],
                "relations": [{"source": "bert", "target": "mlm", "type": "training_objective", "evidence_ids": ["E0006"]}],
                "innovations": [], "must_show": [], "terminology": {},
            },
        }

        spec = normalize_figure_contract(plan, parsed)
        ids = {_item.get("name"): _item.get("id") for field in ("inputs", "modules", "outputs") for _item in spec[field]}
        pairs = {(item["source"], item["target"]) for item in spec["relations"]}

        for label in ("Input Sequence", "Token Embeddings", "Segment Embeddings", "Position Embeddings", "Input Representation"):
            self.assertIn(label, ids)
        self.assertIn((ids["Input Representation"], ids["Bidirectional Transformer Encoder"]), pairs)


if __name__ == "__main__":
    unittest.main()
