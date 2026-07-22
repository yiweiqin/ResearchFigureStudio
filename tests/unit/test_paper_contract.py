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


if __name__ == "__main__":
    unittest.main()
