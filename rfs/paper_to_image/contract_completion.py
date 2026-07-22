from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _label(item: dict[str, Any]) -> str:
    return str(item.get("visible_label") or item.get("name") or item.get("text") or item.get("statement") or item.get("label") or item.get("id") or "").strip()


def _stable_id(prefix: str, label: str) -> str:
    slug = "_".join(part for part in re.sub(r"[^a-z0-9]+", " ", label.casefold()).split() if part)[:48]
    return f"{prefix}_{slug or 'item'}"


@dataclass(frozen=True)
class ConceptRule:
    key: str
    label: str
    field: str
    role: str
    pattern: str
    aliases: tuple[str, ...] = ()
    requires_overview: bool = False


CONCEPT_RULES = (
    ConceptRule("input_image", "Input Image", "inputs", "input", r"\binput images?\b|\bsplit an image\b|\braw image\b|\btest images?\b|\bimages? are shown\b", ("image", "2d image")),
    ConceptRule("images", "Images", "inputs", "input modality", r"\b(?:batch of\s+)?\(?images?\s*[,)]", ("training images", "image batch"), True),
    ConceptRule("image", "Image", "inputs", "input modality", r"\bimages?\s*\+\s*text\b|\bimage encoder\b", ("images", "input image"), True),
    ConceptRule("text", "Text", "inputs", "input modality", r"\b(?:batch of\s+)?\(?image\s*,\s*text\)?|\bimages?\s*\+\s*text\b|\btext training examples?\b", ("captions", "training text", "text batch")),
    ConceptRule("audio", "Audio", "inputs", "input modality", r"\baudio\b", (), True),
    ConceptRule("depth", "Depth", "inputs", "input modality", r"\bdepth\b", (), True),
    ConceptRule("thermal", "Thermal", "inputs", "input modality", r"\bthermal\b", (), True),
    ConceptRule("imu", "IMU", "inputs", "input modality", r"\bimu\b", (), True),
    ConceptRule("prompt", "Prompt", "inputs", "input", r"\b(?:input|segmentation|point|box|mask) prompts?\b|\bprompt encoder\b", ("sparse prompts", "dense prompts", "segmentation prompt"), True),
    ConceptRule("task_input", "Input", "inputs", "input", r"\bgiven an input\b|\btask (?:prompt|instruction)\b", ("task prompt", "task instruction"), True),
    ConceptRule("camera_ray", "Camera Rays", "inputs", "input", r"\bcamera rays?\b", ("camera ray", "ray", "rays")),
    ConceptRule("viewing_direction", "Viewing Direction", "inputs", "conditioning", r"\bview(?:ing)? directions?\b", ("view direction",)),
    ConceptRule("object_queries", "Object Queries", "inputs", "conditioning", r"\bobject quer(?:y|ies)\b", ("learned object queries",)),
    ConceptRule("class_descriptions", "Class Descriptions", "inputs", "conditioning", r"\b(?:names or descriptions|class names|class descriptions|text prompts)\b", ("class names", "text prompts")),
    ConceptRule("cnn_backbone", "CNN Backbone", "modules", "feature extractor", r"\b(?:conventional\s+|common\s+)?cnn backbone\b|\bconvolutional backbone\b", ("backbone", "convolutional backbone")),
    ConceptRule("backbone", "Backbone", "modules", "feature extractor", r"\bbackbones?\b", ("backbone architecture",), True),
    ConceptRule("image_encoder", "Image Encoder", "modules", "encoder", r"\bimage encoder\b"),
    ConceptRule("text_encoder", "Text Encoder", "modules", "encoder", r"\btext encoder\b"),
    ConceptRule("transformer_encoder", "Transformer Encoder", "modules", "encoder", r"\btransformer encoder\b"),
    ConceptRule("transformer_decoder", "Transformer Decoder", "modules", "decoder", r"\btransformer decoder\b"),
    ConceptRule("position_embedding", "Position Embedding", "modules", "conditioning", r"\bposition embeddings?\b", ("positional embedding",), True),
    ConceptRule("positional_encoding", "Positional Encoding", "modules", "conditioning", r"\bposition(?:al)? encod(?:ing|ings)\b", (), True),
    ConceptRule("image_patches", "Image Patches", "modules", "intermediate", r"\bimage patches?\b|\bfixed-size patches\b", ("patches",), True),
    ConceptRule("linear_projection", "Linear Projection of Flattened Patches", "modules", "projection", r"\blinear projection(?: of flattened patches)?\b|\blinearly embed\b", ("linear projection",), True),
    ConceptRule("class_token", "Class Token", "modules", "conditioning", r"\bclass(?:ification)? token\b|\bclass embedding\b", ("classification token", "class embedding"), True),
    ConceptRule("mlp_head", "MLP Head", "modules", "prediction head", r"\bmlp head\b|\bclassification head[^.]{0,100}\bmlp\b"),
    ConceptRule("sampled_points", "Sampled 3D Points", "modules", "intermediate", r"\bsampl(?:e|ed|ing)\s+(?:the\s+)?(?:5d coordinates|3d points)\b|\b5d coordinates\b", ("5d coordinates", "spatial locations")),
    ConceptRule("prediction_ffn", "Feed Forward Network", "modules", "prediction head", r"\bfeed[ -]?forward network\b|\bprediction ffn\b|\bffn\b", ("ffn", "prediction feed-forward network")),
    ConceptRule("region_proposals", "Region Proposals", "modules", "proposal artifact", r"\bregion proposals?\b|\bregion proposal network\b|\brpn\b", ("proposals", "region proposal network (rpn)")),
    ConceptRule("roi_align", "RoIAlign", "modules", "alignment", r"\broialign\b"),
    ConceptRule("generate", "Generate", "modules", "generator", r"\bstarts? by generating\b|\bgenerate(?:s|d| an output)?\b", ("init", "generator"), True),
    ConceptRule("initial_output", "Initial Output", "modules", "artifact", r"\binitial output\b|\bpreviously generated output\b", (), True),
    ConceptRule("feedback", "Feedback", "modules", "feedback provider", r"\bget feedback\b|\breceive feedback\b|\bfeedback provider\b", ("feedback provider",), True),
    ConceptRule("self_feedback", "Self-Feedback", "modules", "feedback artifact", r"\bself[ -]?feedback\b|\bfeedback is passed back\b", ("self-feedback (nl)",), True),
    ConceptRule("refine", "Refine", "modules", "refiner", r"\brefines? the previously generated output\b|\biterate\s*/\s*refine\b", ("refiner",), True),
    ConceptRule("modality_encoders", "Modality Encoders", "modules", "module group", r"\bmodality encoders?\b|\bencoders for each modality\b", ("transformer-based encoders for each modality",)),
    ConceptRule("joint_embedding", "Joint Embedding Space", "modules", "shared representation", r"\b(?:single shared )?(?:joint|common) embedding space\b|\bshared representation space\b", ("joint embedding", "single shared joint embedding space")),
    ConceptRule("prompt_encoder", "Prompt Encoder", "modules", "encoder", r"\bprompt encoder\b"),
    ConceptRule("mask_decoder", "Mask Decoder", "modules", "decoder", r"\bmask decoder\b"),
    ConceptRule("mlp", "MLP", "modules", "neural field", r"\bneural radiance field\b|\bfeeding[^.]{0,100}\bmlp\b|\bmlp to produce\b", ("neural radiance field", "neural network")),
    ConceptRule("image_embeddings", "Image Embeddings", "modules", "representation", r"\bimage embeddings?\b|\bimage features?\b", (), True),
    ConceptRule("text_embeddings", "Text Embeddings", "modules", "representation", r"\btext embeddings?\b|\btext features?\b"),
    ConceptRule("contrastive_objective", "Contrastive Learning", "modules", "training objective", r"\bcontrastive (?:pre-?training|learning|objective|loss)\b|\bcorrect pairings?\b", ("contrastive pre-training", "image-text contrastive loss", "correct pairings")),
    ConceptRule("bipartite_matching", "Bipartite Matching", "modules", "training objective", r"\bbipartite matching\b|\bhungarian matching\b", ("hungarian matching", "set prediction loss")),
    ConceptRule("volume_density", "Volume Density", "modules", "field output", r"\bvolume density\b", ("density", "sigma")),
    ConceptRule("color", "Color", "modules", "field output", r"\b(?:rgb|emitted) colou?r\b|\bradiance\b|\bcolou?r and volume density\b", ("rgb color", "radiance"), True),
    ConceptRule("volume_rendering", "Volume Rendering", "modules", "renderer", r"\b(?:differentiable\s+)?volume rendering\b", ("differentiable volume rendering",)),
    ConceptRule("class_predictions", "Class Predictions", "outputs", "output", r"\bclass (?:prediction|predictions|labels?)\b|\bpredicts?[^.]{0,80}\bclass\b", ("classes", "class labels")),
    ConceptRule("class_prediction", "Class Prediction", "outputs", "output", r"\bimage classification predictions?\b|\bclassification predictions?\b|\bclass label\b", ("image classification predictions", "classification predictions", "class label")),
    ConceptRule("box_predictions", "Bounding Box Predictions", "outputs", "output", r"\bbounding box(?:es| predictions?)?\b|\bbox predictions?\b", ("bounding boxes", "box predictions")),
    ConceptRule("classification", "Classification", "outputs", "output head", r"\bclassification head\b|\bpredicts? the class label\b", ("class label",)),
    ConceptRule("box_regression", "Bounding-box Regression", "outputs", "output head", r"\bbounding[ -]?box regression\b|\bbox regression\b", ("bounding box", "box branch")),
    ConceptRule("mask_branch", "Mask Branch", "outputs", "output head", r"\bmask branch\b"),
    ConceptRule("refined_output", "Refined Output", "outputs", "output", r"\brefined output\b|\bquality of the output improves\b"),
    ConceptRule("emergent_alignment", "Emergent Cross-modal Alignment", "outputs", "output", r"\bemergent (?:cross-modal )?alignments?\b|\bbinding (?:agent|property)\b", ("emergent alignment", "binding agent", "binding property")),
    ConceptRule("valid_mask", "Valid Segmentation Mask", "outputs", "output", r"\bvalid masks?\b|\bobject masks?\b", ("valid masks", "valid mask"), True),
    ConceptRule("zero_shot_classifier", "Zero-Shot Classifier", "outputs", "inference output", r"\bzero[ -]?shot (?:linear )?classifier\b|\bzero[ -]?shot prediction\b", ("zero-shot linear classifier", "zero-shot prediction")),
    ConceptRule("rendered_image", "Rendered Image", "outputs", "output", r"\b(?:rendered|synthesi[sz]ed) (?:images?|views?)\b|\bsynthesi[sz]e images?\b|\bnovel views?\b", ("synthesized image", "synthesized view", "novel view")),
)


RELATION_RULES = (
    ("input_image", "image_patches", "data_flow"),
    ("image_patches", "linear_projection", "data_flow"),
    ("linear_projection", "transformer_encoder", "data_flow"),
    ("position_embedding", "transformer_encoder", "conditioning"),
    ("class_token", "transformer_encoder", "conditioning"),
    ("transformer_encoder", "mlp_head", "data_flow"),
    ("mlp_head", "class_prediction", "data_flow"),
    ("input_image", "cnn_backbone", "data_flow"),
    ("input_image", "backbone", "data_flow"),
    ("cnn_backbone", "transformer_encoder", "data_flow"),
    ("positional_encoding", "transformer_encoder", "conditioning"),
    ("transformer_encoder", "transformer_decoder", "data_flow"),
    ("object_queries", "transformer_decoder", "conditioning"),
    ("transformer_decoder", "prediction_ffn", "data_flow"),
    ("prediction_ffn", "class_predictions", "branch"),
    ("prediction_ffn", "box_predictions", "branch"),
    ("class_predictions", "bipartite_matching", "training_objective"),
    ("box_predictions", "bipartite_matching", "training_objective"),
    ("backbone", "region_proposals", "data_flow"),
    ("region_proposals", "roi_align", "data_flow"),
    ("backbone", "roi_align", "feature_flow"),
    ("roi_align", "classification", "branch"),
    ("roi_align", "class_predictions", "branch"),
    ("roi_align", "box_regression", "branch"),
    ("roi_align", "box_predictions", "branch"),
    ("roi_align", "mask_branch", "branch"),
    ("task_input", "generate", "data_flow"),
    ("generate", "initial_output", "data_flow"),
    ("initial_output", "feedback", "evaluation"),
    ("feedback", "self_feedback", "feedback"),
    ("initial_output", "refine", "revision_input"),
    ("self_feedback", "refine", "feedback"),
    ("refine", "refined_output", "data_flow"),
    ("refined_output", "feedback", "feedback_loop"),
    ("image", "modality_encoders", "encoding"),
    ("text", "modality_encoders", "encoding"),
    ("audio", "modality_encoders", "encoding"),
    ("depth", "modality_encoders", "encoding"),
    ("thermal", "modality_encoders", "encoding"),
    ("imu", "modality_encoders", "encoding"),
    ("modality_encoders", "joint_embedding", "alignment"),
    ("joint_embedding", "emergent_alignment", "enables"),
    ("image", "image_encoder", "data_flow"),
    ("prompt", "prompt_encoder", "data_flow"),
    ("image_encoder", "mask_decoder", "feature_flow"),
    ("prompt_encoder", "mask_decoder", "conditioning"),
    ("mask_decoder", "valid_mask", "data_flow"),
    ("images", "image_encoder", "encoding"),
    ("text", "text_encoder", "encoding"),
    ("image_encoder", "image_embeddings", "data_flow"),
    ("text_encoder", "text_embeddings", "data_flow"),
    ("image_embeddings", "contrastive_objective", "alignment"),
    ("text_embeddings", "contrastive_objective", "alignment"),
    ("class_descriptions", "text_encoder", "encoding"),
    ("image_embeddings", "zero_shot_classifier", "classification"),
    ("text_embeddings", "zero_shot_classifier", "classification"),
    ("camera_ray", "sampled_points", "sampling"),
    ("sampled_points", "positional_encoding", "encoding"),
    ("positional_encoding", "mlp", "data_flow"),
    ("viewing_direction", "mlp", "conditioning"),
    ("mlp", "volume_density", "prediction"),
    ("mlp", "color", "prediction"),
    ("volume_density", "volume_rendering", "rendering_input"),
    ("color", "volume_rendering", "rendering_input"),
    ("volume_rendering", "rendered_image", "data_flow"),
)


def _overview_candidates(parsed: dict[str, Any], limit: int = 2) -> list[dict[str, Any]]:
    positive = re.compile(r"\b(overview|framework|architecture|pipeline|procedure|approach|model|system|workflow|directly predicts)\b", re.IGNORECASE)
    negative = re.compile(r"\b(comparison|performance|result|ablation|visualization|qualitative|attention|distribution)\b", re.IGNORECASE)
    ranked = []
    for index, figure in enumerate(parsed.get("document_index", {}).get("figures", [])):
        caption = str(figure.get("caption") or "")
        score = (8 if positive.search(caption) else 0) + (4 if re.match(r"^(figure|fig\.)\s*[12]\b", caption, re.IGNORECASE) else 0)
        score += 3 if 160 <= len(caption) <= 1600 else 0
        score -= 7 if negative.search(caption) else 0
        ranked.append((score, -index, figure))
    return [item for _, _, item in sorted(ranked, reverse=True)[:limit]]


def _evidence_for_figure(parsed: dict[str, Any], figure: dict[str, Any]) -> dict[str, Any] | None:
    caption = str(figure.get("caption") or "")
    return next(
        (
            item
            for item in parsed.get("evidence", [])
            if item.get("kind") == "caption"
            and item.get("page") == figure.get("page")
            and str(item.get("text") or "").startswith(caption[:60])
        ),
        None,
    )


def _relevant_evidence(parsed: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _overview_candidates(parsed)
    selected = [item for item in (_evidence_for_figure(parsed, figure) for figure in candidates) if item]
    selected_ids = {item["id"] for item in selected}
    page_count = max(1, int(parsed.get("page_count") or 1))
    early_page_limit = max(8, int(page_count * 0.45))
    useful_sections = ("abstract", "introduction", "method", "approach", "architecture", "framework", "model", "system", "figure captions")
    relevant = list(selected)
    for item in parsed.get("evidence", []):
        if item.get("id") in selected_ids:
            continue
        section = str(item.get("section_hint") or "").casefold()
        if any(term in section for term in ("reference", "acknowledg")):
            continue
        if int(item.get("page") or page_count + 1) <= early_page_limit or any(term in section for term in useful_sections):
            relevant.append(item)
    return selected, relevant


def _find_matches(rule: ConceptRule, selected: list[dict[str, Any]], relevant: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pattern = re.compile(rule.pattern, re.IGNORECASE)
    primary = [item for item in selected if pattern.search(str(item.get("text") or ""))]
    if primary:
        return primary[:2]
    if rule.requires_overview:
        return []
    secondary = [item for item in relevant if pattern.search(str(item.get("text") or ""))]
    return secondary[:2]


def _find_existing(spec: dict[str, Any], rule: ConceptRule) -> tuple[str, dict[str, Any]] | None:
    accepted = {_normalized(rule.key), _normalized(rule.label), *(_normalized(value) for value in rule.aliases)}
    for field in ("inputs", "modules", "outputs", "innovations"):
        for item in spec.get(field, []) if isinstance(spec.get(field), list) else []:
            if not isinstance(item, dict):
                continue
            value = _normalized(_label(item))
            item_id = _normalized(item.get("id"))
            if item_id in accepted or value in accepted:
                return field, item
            if rule.key != "self_feedback" and field == rule.field and len(value) >= 8 and any(len(candidate) >= 8 and (value in candidate or candidate in value) for candidate in accepted if candidate):
                return field, item
    return None


def augment_contract_from_evidence(spec: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    selected, relevant = _relevant_evidence(parsed)
    found: dict[str, dict[str, Any]] = {}
    added_entities: list[str] = []
    upgraded_entities: list[str] = []
    adopted_entities: list[str] = []
    for rule in CONCEPT_RULES:
        matches = _find_matches(rule, selected, relevant)
        if not matches:
            continue
        evidence_ids = list(dict.fromkeys(str(item.get("id")) for item in matches if item.get("id")))
        existing = _find_existing(spec, rule)
        if existing:
            _, item = existing
            current = _label(item)
            if str(item.get("role") or "") == "paper-derived stage requiring VLM verification":
                item["role"] = rule.role
                adopted_entities.append(str(item.get("id") or rule.key))
            if _normalized(current) != _normalized(rule.label) and (_normalized(current) in _normalized(rule.label) or current.casefold().startswith(("neural network module", "learned "))):
                item["name"] = rule.label
                upgraded_entities.append(str(item.get("id") or rule.key))
            item["evidence_ids"] = list(dict.fromkeys(list(item.get("evidence_ids", [])) + evidence_ids))
            found[rule.key] = item
            continue
        item = {"id": _stable_id(rule.field.rstrip("s"), rule.label), "name": rule.label, "role": rule.role, "evidence_ids": evidence_ids}
        spec.setdefault(rule.field, []).append(item)
        found[rule.key] = item
        added_entities.append(item["id"])

    for rule in CONCEPT_RULES:
        if rule.key not in found:
            existing = _find_existing(spec, rule)
            if existing:
                found[rule.key] = existing[1]

    relations = spec.setdefault("relations", [])
    existing_pairs = {(str(item.get("source")), str(item.get("target"))) for item in relations if isinstance(item, dict)}
    selected_ids = [str(item.get("id")) for item in selected if item.get("id")]
    evidence_by_id = {str(item.get("id")): item for item in relevant if item.get("id")}
    added_relations: list[str] = []
    for source_key, target_key, relation_type in RELATION_RULES:
        source = found.get(source_key)
        target = found.get(target_key)
        if not source or not target:
            continue
        pair = (str(source.get("id")), str(target.get("id")))
        if pair in existing_pairs:
            continue
        evidence_ids = list(dict.fromkeys(list(source.get("evidence_ids", [])) + list(target.get("evidence_ids", []))))
        if selected_ids and not any(value in selected_ids for value in evidence_ids):
            source_text = _label(source).casefold()
            target_text = _label(target).casefold()
            bridge = next((item for item in relevant if source_text.split()[-1] in str(item.get("text") or "").casefold() and target_text.split()[-1] in str(item.get("text") or "").casefold()), None)
            source_pages = [int(evidence_by_id[value].get("page") or 0) for value in source.get("evidence_ids", []) if value in evidence_by_id]
            target_pages = [int(evidence_by_id[value].get("page") or 0) for value in target.get("evidence_ids", []) if value in evidence_by_id]
            nearby = bool(source_pages and target_pages and min(abs(left - right) for left in source_pages for right in target_pages) <= 3)
            if not bridge and not nearby:
                continue
            if bridge:
                evidence_ids.append(str(bridge.get("id")))
        relations.append({"source": pair[0], "target": pair[1], "type": relation_type, "label": "", "evidence_ids": list(dict.fromkeys(evidence_ids))})
        existing_pairs.add(pair)
        added_relations.append(f"{pair[0]}->{pair[1]}")

    overview_terms = [rule.key for rule in CONCEPT_RULES if _find_matches(rule, selected, [])]
    covered_terms = [key for key in overview_terms if key in found]
    return {
        "summary": "Conservative evidence-driven contract completion report.",
        "selected_overview_evidence_ids": selected_ids,
        "overview_term_count": len(overview_terms),
        "covered_overview_term_count": len(covered_terms),
        "overview_term_coverage": round(len(covered_terms) / max(1, len(overview_terms)), 4),
        "added_entities": added_entities,
        "upgraded_entities": upgraded_entities,
        "adopted_entities": adopted_entities,
        "added_relations": added_relations,
        "rules_are_evidence_gated": True,
    }
