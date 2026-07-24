from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..utils import ensure_dir, write_json
from ..vlm_client import call_vlm_json, resolve_vlm_model, vlm_credentials_available
from .semantic_blueprint import compile_semantic_blueprint


BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "dense-multiframe": {
        "summary": "Dense three-panel overview combining task semantics, model internals, and a staged data engine.",
        "template_id": "dense-multiframe",
        "name": "Task, model, and data-engine overview",
        "aspect_ratio": 1.78,
        "topology": ["three_macro_panels", "nested_model_flow", "staged_data_engine", "model_to_data_feedback"],
        "ideal_module_range": [8, 16],
        "visual_density": "very_high",
        "panels": [
            {"id": "task", "role": "promptable_task", "bbox_percent": {"x": 0.02, "y": 0.08, "w": 0.27, "h": 0.84}},
            {"id": "model", "role": "model_architecture", "bbox_percent": {"x": 0.34, "y": 0.08, "w": 0.34, "h": 0.84}},
            {"id": "data", "role": "data_engine", "bbox_percent": {"x": 0.73, "y": 0.08, "w": 0.25, "h": 0.84}},
        ],
        "connectors": ["image_to_image_encoder", "prompt_to_prompt_encoder", "encoders_to_decoder", "decoder_to_mask", "three_stage_data_engine", "model_to_data_engine_support"],
        "style": {"background": "white", "panel_fill": "soft_tint", "stroke": "muted_blue", "accent": ["blue", "green", "orange"], "corners": "rounded", "shadow": "soft_cards"},
    },
    "multimodal": {
        "summary": "Multiple modality inputs converge through modality encoders into one joint embedding space and an emergent alignment output.",
        "template_id": "multimodal",
        "name": "Multimodal convergence into a shared space",
        "aspect_ratio": 1.78,
        "topology": ["many_inputs", "encoder_bank", "many_to_one", "joint_embedding", "emergent_alignment"],
        "ideal_module_range": [2, 5],
        "visual_density": "high",
        "panels": [
            {"id": "modalities", "role": "stacked_modality_inputs", "bbox_percent": {"x": 0.02, "y": 0.06, "w": 0.25, "h": 0.88}},
            {"id": "encoders", "role": "modality_encoder_bank", "bbox_percent": {"x": 0.34, "y": 0.18, "w": 0.20, "h": 0.64}},
            {"id": "embedding", "role": "joint_embedding_space", "bbox_percent": {"x": 0.61, "y": 0.23, "w": 0.18, "h": 0.54}},
            {"id": "alignment", "role": "emergent_alignment_output", "bbox_percent": {"x": 0.84, "y": 0.28, "w": 0.14, "h": 0.44}},
        ],
        "connectors": ["each_modality_to_encoder_bank", "encoder_bank_to_joint_embedding", "joint_embedding_to_emergent_alignment"],
        "style": {"background": "white", "panel_fill": "near_white", "stroke": "muted_indigo", "accent": ["blue", "violet", "orange", "teal"], "corners": "rounded", "shadow": "soft_cards"},
    },
    "branch": {
        "summary": "Shared-trunk architecture with proposal convergence and parallel output heads.",
        "template_id": "branch",
        "name": "Shared trunk with parallel heads",
        "aspect_ratio": 1.78,
        "topology": ["left_to_right", "shared_backbone", "convergence", "three_way_branch"],
        "ideal_module_range": [4, 10],
        "visual_density": "high",
        "panels": [
            {"id": "input", "role": "input", "bbox_percent": {"x": 0.02, "y": 0.28, "w": 0.13, "h": 0.44}},
            {"id": "backbone", "role": "shared_backbone", "bbox_percent": {"x": 0.19, "y": 0.22, "w": 0.18, "h": 0.56}},
            {"id": "proposals", "role": "proposal_path", "bbox_percent": {"x": 0.40, "y": 0.10, "w": 0.16, "h": 0.28}},
            {"id": "alignment", "role": "feature_proposal_convergence", "bbox_percent": {"x": 0.43, "y": 0.48, "w": 0.17, "h": 0.25}},
            {"id": "heads", "role": "parallel_output_heads", "bbox_percent": {"x": 0.68, "y": 0.14, "w": 0.28, "h": 0.72}},
        ],
        "connectors": ["input_to_backbone", "backbone_to_proposals", "backbone_features_to_alignment", "proposals_to_alignment", "alignment_three_way_split"],
        "style": {"background": "white", "panel_fill": "near_white", "stroke": "muted_blue", "accent": ["blue", "orange", "green"], "corners": "rounded", "shadow": "soft_cards"},
    },
    "feedback": {
        "summary": "Compact two-row iterative generation, feedback, and refinement template.",
        "template_id": "feedback",
        "name": "Feedback refinement loop",
        "aspect_ratio": 1.78,
        "topology": ["feedback", "iteration", "two_row_loop", "shared_model"],
        "ideal_module_range": [4, 9],
        "visual_density": "high",
        "panels": [
            {"id": "task_input", "role": "input", "bbox_percent": {"x": 0.02, "y": 0.12, "w": 0.12, "h": 0.24}},
            {"id": "generation", "role": "initial_generation", "bbox_percent": {"x": 0.18, "y": 0.10, "w": 0.20, "h": 0.28}},
            {"id": "initial_output", "role": "initial_output", "bbox_percent": {"x": 0.42, "y": 0.10, "w": 0.18, "h": 0.28}},
            {"id": "feedback", "role": "self_feedback", "bbox_percent": {"x": 0.70, "y": 0.10, "w": 0.22, "h": 0.36}},
            {"id": "refinement", "role": "refinement", "bbox_percent": {"x": 0.42, "y": 0.62, "w": 0.20, "h": 0.25}},
            {"id": "refined_output", "role": "refined_output", "bbox_percent": {"x": 0.68, "y": 0.62, "w": 0.20, "h": 0.25}},
        ],
        "connectors": ["input_to_generation", "generation_to_initial_output", "initial_output_to_feedback", "initial_output_to_refinement", "feedback_to_refinement", "refinement_to_refined_output", "refined_output_to_feedback_loop"],
        "style": {"background": "white", "panel_fill": "near_white", "stroke": "muted_blue", "accent": ["navy", "teal", "orange"], "corners": "rounded", "shadow": "soft_cards"},
    },
    "arbor": {
        "summary": "Tree-centered iterative research template.",
        "template_id": "arbor",
        "name": "Arbor tree-loop",
        "aspect_ratio": 1.87,
        "topology": ["tree", "loop", "feedback", "side_inputs", "side_outputs", "top_phase_ribbon"],
        "ideal_module_range": [6, 16],
        "visual_density": "very_high",
        "panels": [
            {"id": "phase_ribbon", "role": "phase_ribbon", "bbox_percent": {"x": 0.13, "y": 0.03, "w": 0.84, "h": 0.14}},
            {"id": "left_inputs", "role": "inputs", "bbox_percent": {"x": 0.02, "y": 0.25, "w": 0.14, "h": 0.55}},
            {"id": "central_tree", "role": "core_method", "bbox_percent": {"x": 0.21, "y": 0.22, "w": 0.61, "h": 0.56}},
            {"id": "right_outputs", "role": "outputs", "bbox_percent": {"x": 0.85, "y": 0.34, "w": 0.13, "h": 0.42}},
            {"id": "bottom_executors", "role": "execution", "bbox_percent": {"x": 0.32, "y": 0.83, "w": 0.43, "h": 0.13}},
        ],
        "connectors": ["large_clockwise_loop", "tree_branches", "left_to_center", "center_to_right"],
        "style": {"background": "white", "panel_fill": "paper_tint", "stroke": "muted_blue", "accent": ["green", "blue", "red"], "corners": "rounded", "shadow": "minimal"},
    },
    "linear": {
        "summary": "Ultra-wide sequential research workflow template.",
        "template_id": "linear",
        "name": "Ultra-wide linear stages",
        "aspect_ratio": 4.366,
        "topology": ["linear", "four_to_six_stages", "local_feedback_loops"],
        "ideal_module_range": [4, 8],
        "visual_density": "high",
        "panels": [
            {"id": "stage_1", "role": "input_problem", "bbox_percent": {"x": 0.01, "y": 0.08, "w": 0.18, "h": 0.82}},
            {"id": "stage_2", "role": "knowledge", "bbox_percent": {"x": 0.20, "y": 0.08, "w": 0.24, "h": 0.82}},
            {"id": "stage_3", "role": "core_method", "bbox_percent": {"x": 0.45, "y": 0.08, "w": 0.27, "h": 0.82}},
            {"id": "stage_4", "role": "output", "bbox_percent": {"x": 0.73, "y": 0.08, "w": 0.26, "h": 0.82}},
        ],
        "connectors": ["left_to_right", "small_feedback_loops"],
        "style": {"background": "white", "panel_fill": "soft_pastel", "stroke": "dark_gray", "accent": ["blue", "yellow"], "corners": "slightly_rounded", "shadow": "soft_cards"},
    },
    "tripanel": {
        "summary": "Three-panel multimodal indexing and retrieval template.",
        "template_id": "tripanel",
        "name": "Three-panel retrieval pipeline",
        "aspect_ratio": 2.903,
        "topology": ["three_panels", "data_to_index_to_query", "parallel_channels"],
        "ideal_module_range": [5, 12],
        "visual_density": "high",
        "panels": [
            {"id": "panel_a", "role": "data_sources", "bbox_percent": {"x": 0.02, "y": 0.05, "w": 0.16, "h": 0.84}},
            {"id": "panel_b", "role": "indexing", "bbox_percent": {"x": 0.20, "y": 0.05, "w": 0.45, "h": 0.84}},
            {"id": "panel_c", "role": "query_and_output", "bbox_percent": {"x": 0.67, "y": 0.05, "w": 0.31, "h": 0.84}},
        ],
        "connectors": ["left_to_right", "parallel_modalities", "retrieval_merge"],
        "style": {"background": "white", "panel_fill": "near_white", "stroke": "dashed_colored", "accent": ["blue", "peach", "purple"], "corners": "rounded", "shadow": "none"},
    },
    "dense-multimodal": {
        "summary": "Dense multimodal parsing, grounding, retrieval, and response template.",
        "template_id": "dense-multimodal",
        "name": "Dense multimodal system",
        "aspect_ratio": 2.3,
        "topology": ["multi_input", "dense_panels", "knowledge_graph", "retrieval", "response"],
        "ideal_module_range": [9, 20],
        "visual_density": "very_high",
        "panels": [
            {"id": "inputs", "role": "multi_source_inputs", "bbox_percent": {"x": 0.01, "y": 0.06, "w": 0.07, "h": 0.86}},
            {"id": "parsing", "role": "content_parsing", "bbox_percent": {"x": 0.09, "y": 0.05, "w": 0.24, "h": 0.87}},
            {"id": "grounding", "role": "knowledge_grounding", "bbox_percent": {"x": 0.34, "y": 0.05, "w": 0.48, "h": 0.87}},
            {"id": "query", "role": "query_retrieval_response", "bbox_percent": {"x": 0.83, "y": 0.05, "w": 0.16, "h": 0.87}},
        ],
        "connectors": ["left_to_right", "parallel_processing", "merge", "query_response"],
        "style": {"background": "white", "panel_fill": "transparent", "stroke": "hand_drawn_dashed_blue", "accent": ["pastel_blue", "peach", "mint", "lavender"], "corners": "rounded", "shadow": "none"},
    },
}


def _dominant_colors(path: Path, count: int = 6) -> list[str]:
    with Image.open(path) as image:
        thumb = image.convert("RGB").resize((96, 96)).quantize(colors=count).convert("RGB")
        colors = sorted(thumb.getcolors(96 * 96) or [], reverse=True)
    return [f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}" for _amount, rgb in colors[:count]]


def _classify_by_ratio(ratio: float) -> str:
    if ratio >= 3.5:
        return "linear"
    if ratio >= 2.55:
        return "tripanel"
    if ratio >= 2.05:
        return "dense-multimodal"
    return "arbor"


def _vlm_template_analysis(path: Path, base: dict, model: str | None) -> dict:
    prompt = f"""
# Summary

Analyze this scientific framework figure only as a reusable architecture and style template. Return JSON only. Do not summarize its scientific content for reuse.

Base archetype:
{json.dumps(base, ensure_ascii=False, indent=2)}

Return:
{{
  "summary": "Reference template analysis.",
  "macro_structure": [],
  "reading_order": [],
  "connector_rhythm": [],
  "visual_focus": [],
  "typography": {{"hierarchy": [], "density": "..."}},
  "style_adjustments": {{}},
  "forbidden_copy_terms": ["all visible paper-specific terms, method names, dataset names, captions, and branded labels found in the image"],
  "forbidden_copy_objects": ["paper-specific logos or uniquely identifying objects"]
}}
""".strip()
    resolved = resolve_vlm_model("RFS_TEMPLATE_ANALYZER_MODEL", "RFS_PAPER_TO_IMAGE_MODEL", explicit_model=model)
    result = call_vlm_json(prompt, [path], model=resolved, timeout=180, retries=1)
    result.setdefault("summary", "Reference template analysis.")
    result["model"] = resolved
    return result


def build_template_profiles(reference_paths: list[str], out_dir: str | Path, mode: str = "vlm", model: str | None = None) -> list[dict]:
    out = ensure_dir(out_dir)
    profiles = []
    for index, value in enumerate(reference_paths):
        path = Path(value).resolve()
        with Image.open(path) as image:
            width, height = image.size
        ratio = width / max(height, 1)
        archetype = _classify_by_ratio(ratio)
        base = json.loads(json.dumps(BUILTIN_TEMPLATES[archetype]))
        profile = {
            **base,
            "summary": "Content-free reference template profile.",
            "profile_id": f"reference_{index + 1:02d}_{archetype}",
            "source_reference": str(path),
            "source_pixels": {"width": width, "height": height},
            "source_aspect_ratio": round(ratio, 6),
            "palette": _dominant_colors(path),
            "analysis_mode": "heuristic",
            "forbidden_copy_terms": [],
            "forbidden_copy_objects": [],
        }
        if mode == "vlm" and vlm_credentials_available():
            try:
                analysis = _vlm_template_analysis(path, base, model)
                profile.update({key: value for key, value in analysis.items() if key not in {"summary"}})
                profile["analysis_mode"] = "vlm"
            except Exception as exc:
                profile["analysis_warning"] = str(exc)
        write_json(out / f"{profile['profile_id']}.json", profile)
        profiles.append(profile)
    if not profiles:
        for archetype, base in BUILTIN_TEMPLATES.items():
            profile = {**json.loads(json.dumps(base)), "profile_id": f"builtin_{archetype}", "source_reference": None, "source_aspect_ratio": base["aspect_ratio"], "palette": [], "analysis_mode": "builtin", "forbidden_copy_terms": [], "forbidden_copy_objects": []}
            write_json(out / f"{profile['profile_id']}.json", profile)
            profiles.append(profile)
    return profiles


def _paper_features(review: dict) -> dict:
    statements = " ".join(str(item.get("statement", "")) for field in ["research_questions", "central_claims", "inputs", "modules", "relations", "innovations"] for item in review.get(field, [])).lower()
    relation_types = {str(item.get("relation_type") or item.get("type") or "").lower() for item in review.get("relations", [])}
    workflow = review.get("workflows", {})
    input_labels = " ".join(str(item.get("visible_label") or item.get("statement") or "").lower() for item in review.get("inputs", []))
    modality_count = sum(term in input_labels for term in ("image", "text", "audio", "video", "depth", "thermal", "imu"))
    return {
        "module_count": len(review.get("modules", [])),
        "input_count": len(review.get("inputs", [])),
        "has_loop": bool(workflow.get("feedback")) or "feedback" in relation_types or any(token in statements for token in ["iterative", "loop", "tree search", "backpropagate"]),
        "has_tree": any(token in statements for token in ["tree", "prune", "tree search", "search tree"]),
        "has_branch": any(token in statements for token in ["branch", "parallel head", "parallel output", "multi-head", "multihead"]),
        "modality_count": modality_count,
        "has_multimodal": modality_count >= 3 or any(token in statements for token in ["multimodal", "multi-modal", "cross-modal", "cross modal"]),
        "has_retrieval": any(token in statements for token in ["retrieval", "retrieve", "index", "rag", "knowledge graph"]),
    }


def select_template(profiles: list[dict], review: dict, requested: str = "auto", target_ratio: str = "auto", contract_topology: str | None = None) -> dict:
    if requested != "auto":
        matches = [profile for profile in profiles if profile.get("template_id") == requested or profile.get("profile_id") == requested]
        if not matches:
            builtin = BUILTIN_TEMPLATES.get(requested)
            if not builtin:
                raise ValueError(f"Requested template not found: {requested}")
            matches = [{**json.loads(json.dumps(builtin)), "profile_id": f"builtin_{requested}", "source_reference": None, "source_aspect_ratio": builtin["aspect_ratio"], "palette": [], "analysis_mode": "builtin", "forbidden_copy_terms": [], "forbidden_copy_objects": []}]
        selected = dict(matches[0])
        selected["selection"] = {"mode": "explicit", "score": 1.0, "reasons": ["explicit CLI selection"]}
        return selected
    features = _paper_features(review)
    requested_ratio = None
    if target_ratio != "auto":
        try:
            left, right = target_ratio.split(":", 1)
            requested_ratio = float(left) / float(right)
        except Exception:
            requested_ratio = None
    scored = []
    for profile in profiles:
        template_id = profile["template_id"]
        low, high = profile.get("ideal_module_range", [1, 99])
        module_fit = 1.0 if low <= features["module_count"] <= high else max(0.0, 1.0 - min(abs(features["module_count"] - low), abs(features["module_count"] - high)) / 10)
        topology = 0.0
        reasons = [f"module_fit={module_fit:.2f}"]
        topology_template = {"dense_multiframe": "dense-multiframe"}.get(str(contract_topology or ""), str(contract_topology or ""))
        if topology_template and template_id == topology_template:
            topology += 1.5; reasons.append(f"normalized contract topology={contract_topology}")
        if template_id == "feedback" and features["has_loop"] and not features["has_tree"]:
            topology += 1.0; reasons.append("explicit feedback-loop topology")
        if template_id == "branch" and features["has_branch"] and not features["has_loop"] and not features["has_tree"] and not features["has_multimodal"] and not features["has_retrieval"]:
            topology += 1.0; reasons.append("shared-trunk parallel-branch topology")
        if template_id == "multimodal" and features["has_multimodal"] and features["modality_count"] >= 3 and features["module_count"] < 8:
            topology += 1.1; reasons.append("multiple modalities converge into a shared representation")
        if template_id == "arbor" and features["has_tree"]:
            topology += 1.0; reasons.append("tree/branch topology")
        if template_id == "linear" and not features["has_loop"] and not features["has_tree"] and not features["has_branch"] and not features["has_retrieval"] and 2 <= features["module_count"] <= 8:
            topology += 0.9; reasons.append("sequential stage count")
        if template_id == "tripanel" and features["has_retrieval"]:
            topology += 0.9; reasons.append("index/retrieval topology")
        if template_id == "dense-multimodal" and features["has_multimodal"] and features["module_count"] >= 8:
            topology += 1.0; reasons.append("dense multimodal topology")
        ratio_score = 0.5
        if requested_ratio:
            ratio_score = max(0.0, 1.0 - abs(float(profile.get("source_aspect_ratio") or profile["aspect_ratio"]) - requested_ratio) / max(requested_ratio, 0.1))
        score = 0.45 * module_fit + 0.40 * min(topology, 1.0) + 0.15 * ratio_score
        scored.append((score, profile, reasons + [f"ratio_fit={ratio_score:.2f}"]))
    score, profile, reasons = max(scored, key=lambda item: item[0])
    selected = dict(profile)
    selected["selection"] = {"mode": "automatic", "score": round(score, 4), "reasons": reasons, "paper_features": features}
    return selected


def _canvas_size(profile: dict, target_ratio: str) -> tuple[int, int, float]:
    ratio = float(profile.get("source_aspect_ratio") or profile.get("aspect_ratio") or 16 / 9)
    if target_ratio != "auto":
        try:
            left, right = target_ratio.split(":", 1)
            ratio = float(left) / float(right)
        except Exception:
            pass
    if ratio >= 1:
        width = 1536
        height = max(512, round(width / ratio))
    else:
        height = 1536
        width = max(512, round(height * ratio))
    return width, height, ratio


def render_layout_blueprint(
    profile: dict,
    out_path: str | Path,
    target_ratio: str = "auto",
    figure_specification: dict[str, Any] | None = None,
) -> dict:
    width, height, ratio = _canvas_size(profile, target_ratio)
    image = Image.new("RGB", (width, height), (250, 250, 249))
    draw = ImageDraw.Draw(image)
    panels = profile.get("panels", [])

    def normalized(value: Any) -> str:
        return "".join(char for char in str(value or "").casefold() if char.isalnum())

    exact_labels: dict[str, str] = {}
    if figure_specification:
        for field in ("inputs", "modules", "outputs", "innovations"):
            for item in figure_specification.get(field, []) if isinstance(figure_specification.get(field), list) else []:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("name") or item.get("label") or item.get("title") or "").strip()
                if label:
                    exact_labels[normalized(label)] = label
        for label in figure_specification.get("required_labels", []) if isinstance(figure_specification.get("required_labels"), list) else []:
            if str(label).strip():
                exact_labels.setdefault(normalized(label), str(label).strip())

    def exact(canonical: str) -> str:
        return exact_labels.get(normalized(canonical), canonical)

    feedback_required = {
        normalized(value)
        for value in ("input x", "Generate", "Initial Output", "FEEDBACK", "Self-Feedback", "REFINE", "Refined output", "Model M")
    }
    semantic_feedback = profile.get("template_id") == "feedback" and feedback_required.issubset(exact_labels)
    dense_required = {
        normalized(value)
        for value in (
            "Promptable Segmentation Task", "Segment Anything Model", "Data Engine", "Image", "Prompt",
            "Image Encoder", "Prompt Encoder", "Mask Decoder", "Valid Segmentation Mask",
            "Assisted-manual", "Semi-automatic", "Fully Automatic", "SA-1B",
        )
    }
    semantic_dense = profile.get("template_id") == "dense-multiframe" and dense_required.issubset(exact_labels)
    generic_semantic_plan = compile_semantic_blueprint(figure_specification)
    semantic_generic = bool(generic_semantic_plan.get("applied")) and not semantic_feedback and not semantic_dense
    semantic_blueprint = semantic_feedback or semantic_dense or semantic_generic
    if semantic_generic:
        panels = []

    def font(size: int, bold: bool = False):
        candidates = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, max(12, size))
            except OSError:
                continue
        return ImageFont.load_default()

    def centered_text(box: tuple[int, int, int, int], value: str, size: int, fill=(42, 72, 91), bold: bool = True) -> None:
        fitted_size = max(12, size)
        selected_font = font(fitted_size, bold=bold)
        bounds = draw.textbbox((0, 0), value, font=selected_font)
        available_width = max(8, box[2] - box[0] - 12)
        while bounds[2] - bounds[0] > available_width and fitted_size > 12:
            fitted_size -= 1
            selected_font = font(fitted_size, bold=bold)
            bounds = draw.textbbox((0, 0), value, font=selected_font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        x = box[0] + ((box[2] - box[0]) - text_width) / 2
        y = box[1] + ((box[3] - box[1]) - text_height) / 2 - bounds[1]
        draw.text((x, y), value, font=selected_font, fill=fill)

    def centered_wrapped_text(box: tuple[int, int, int, int], value: str, size: int, fill=(42, 72, 91), bold: bool = True) -> None:
        max_width = max(20, box[2] - box[0] - 14)
        max_height = max(20, box[3] - box[1] - 10)
        tokens = value.split() if " " in value.strip() else list(value.strip())
        selected_font = font(size, bold=bold)
        selected_lines = [value]
        for fitted_size in range(max(10, size), 9, -1):
            selected_font = font(fitted_size, bold=bold)
            lines: list[str] = []
            current = ""
            separator = " " if " " in value.strip() else ""
            for token in tokens:
                candidate = token if not current else f"{current}{separator}{token}"
                if draw.textlength(candidate, font=selected_font) <= max_width or not current:
                    current = candidate
                else:
                    lines.append(current)
                    current = token
            if current:
                lines.append(current)
            if len(lines) > 3:
                continue
            text_value = "\n".join(lines)
            bounds = draw.multiline_textbbox((0, 0), text_value, font=selected_font, spacing=3, align="center")
            if bounds[2] - bounds[0] <= max_width and bounds[3] - bounds[1] <= max_height:
                selected_lines = lines
                break
        text_value = "\n".join(selected_lines)
        bounds = draw.multiline_textbbox((0, 0), text_value, font=selected_font, spacing=3, align="center")
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        x = box[0] + ((box[2] - box[0]) - text_width) / 2
        y = box[1] + ((box[3] - box[1]) - text_height) / 2 - bounds[1]
        draw.multiline_text((x, y), text_value, font=selected_font, fill=fill, spacing=3, align="center")

    centers = []
    panel_boxes = []
    for index, panel in enumerate(panels):
        bbox = panel["bbox_percent"]
        x0, y0 = int(bbox["x"] * width), int(bbox["y"] * height)
        x1, y1 = int((bbox["x"] + bbox["w"]) * width), int((bbox["y"] + bbox["h"]) * height)
        fill = (241 + (index % 2) * 4, 246, 247 - (index % 3) * 2)
        dash = profile["template_id"] in {"tripanel", "dense-multimodal"}
        if dash:
            segment = max(8, round(width * 0.006))
            for x in range(x0, x1, segment * 2):
                draw.line((x, y0, min(x + segment, x1), y0), fill=(104, 132, 151), width=3)
                draw.line((x, y1, min(x + segment, x1), y1), fill=(104, 132, 151), width=3)
            for y in range(y0, y1, segment * 2):
                draw.line((x0, y, x0, min(y + segment, y1)), fill=(104, 132, 151), width=3)
                draw.line((x1, y, x1, min(y + segment, y1)), fill=(104, 132, 151), width=3)
            draw.rectangle((x0 + 4, y0 + 4, x1 - 4, y1 - 4), fill=fill)
        else:
            draw.rounded_rectangle((x0, y0, x1, y1), radius=max(10, round(height * 0.025)), fill=fill, outline=(104, 132, 151), width=3)
        centers.append(((x0 + x1) // 2, (y0 + y1) // 2))
        panel_boxes.append((x0, y0, x1, y1))
        if not semantic_blueprint:
            slots = max(2, min(6, round((x1 - x0) / max(width * 0.12, 1))))
            for slot_index in range(slots):
                sx0 = x0 + int((slot_index + 0.2) / slots * (x1 - x0))
                sx1 = x0 + int((slot_index + 0.8) / slots * (x1 - x0))
                sy0 = y0 + int(0.28 * (y1 - y0))
                sy1 = y0 + int(0.70 * (y1 - y0))
                draw.rounded_rectangle((sx0, sy0, sx1, sy1), radius=8, outline=(178, 190, 198), width=2)
    def draw_arrow_path(points: list[tuple[int, int]], color: tuple[int, int, int] = (80, 111, 134)) -> None:
        draw.line(points, fill=color, width=4, joint="curve")
        if len(points) < 2:
            return
        tail, end = points[-2], points[-1]
        angle = math.atan2(end[1] - tail[1], end[0] - tail[0])
        arrow = 12
        points = [end, (end[0] - arrow * math.cos(angle - 0.45), end[1] - arrow * math.sin(angle - 0.45)), (end[0] - arrow * math.cos(angle + 0.45), end[1] - arrow * math.sin(angle + 0.45))]
        draw.polygon(points, fill=color)

    def region(box, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (
            round(box[0] + x0 * (box[2] - box[0])),
            round(box[1] + y0 * (box[3] - box[1])),
            round(box[0] + x1 * (box[2] - box[0])),
            round(box[1] + y1 * (box[3] - box[1])),
        )

    def draw_dashed_arrow(start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int] = (177, 92, 33)) -> None:
        length = max(1, end[0] - start[0])
        dash = max(10, round(width * 0.008))
        gap = max(7, round(width * 0.005))
        cursor = 0
        while cursor < length - 16:
            draw.line((start[0] + cursor, start[1], min(end[0] - 16, start[0] + cursor + dash), end[1]), fill=color, width=4)
            cursor += dash + gap
        draw_arrow_path([(end[0] - 18, end[1]), end], color)

    if profile.get("template_id") == "feedback" and len(panel_boxes) >= 6:
        def left(box): return (box[0], (box[1] + box[3]) // 2)
        def right(box): return (box[2], (box[1] + box[3]) // 2)
        def top_at(box, fraction): return (round(box[0] + fraction * (box[2] - box[0])), box[1])
        def bottom_at(box, fraction): return (round(box[0] + fraction * (box[2] - box[0])), box[3])
        input_box, generation_box, initial_box, feedback_box, refinement_box, refined_box = panel_boxes[:6]
        draw_arrow_path([right(input_box), left(generation_box)])
        draw_arrow_path([right(generation_box), left(initial_box)])
        draw_arrow_path([right(initial_box), left(feedback_box)])
        initial_start, initial_end = bottom_at(initial_box, 0.45), top_at(refinement_box, 0.35)
        initial_mid_y = round((initial_start[1] + initial_end[1]) / 2)
        draw_arrow_path([initial_start, (initial_start[0], initial_mid_y), (initial_end[0], initial_mid_y), initial_end], (31, 117, 126))
        feedback_start, feedback_end = bottom_at(feedback_box, 0.50), top_at(refinement_box, 0.72)
        feedback_mid_y = round((feedback_start[1] + feedback_end[1]) / 2)
        draw_arrow_path([feedback_start, (feedback_start[0], feedback_mid_y), (feedback_end[0], feedback_mid_y), feedback_end], (31, 117, 126))
        draw_arrow_path([right(refinement_box), left(refined_box)], (31, 117, 126))
        loop_start = right(refined_box)
        loop_end = (feedback_box[2], round(feedback_box[1] + 0.70 * (feedback_box[3] - feedback_box[1])))
        loop_x = min(width - 18, max(loop_start[0], loop_end[0]) + round(width * 0.045))
        draw_arrow_path([loop_start, (loop_x, loop_start[1]), (loop_x, loop_end[1]), loop_end], (31, 117, 126))
        if semantic_feedback:
            input_box, generation_box, initial_box, feedback_box, refinement_box, refined_box = panel_boxes[:6]
            title_size = max(16, round(height * 0.025))
            badge_size = max(14, round(height * 0.020))
            centered_text(region(input_box, 0.05, 0.30, 0.95, 0.70), exact("input x"), title_size)
            centered_text(region(generation_box, 0.05, 0.06, 0.95, 0.35), exact("Generate"), title_size)
            centered_text(region(initial_box, 0.04, 0.20, 0.96, 0.52), exact("Initial Output"), title_size)
            centered_text(region(feedback_box, 0.05, 0.04, 0.95, 0.25), exact("FEEDBACK"), title_size, fill=(177, 92, 33))
            centered_text(region(refinement_box, 0.05, 0.06, 0.95, 0.34), exact("REFINE"), title_size)
            centered_text(region(refined_box, 0.04, 0.20, 0.96, 0.52), exact("Refined output"), title_size)

            for badge_box in (
                region(generation_box, 0.24, 0.48, 0.76, 0.76),
                region(feedback_box, 0.30, 0.27, 0.70, 0.47),
                region(refinement_box, 0.24, 0.48, 0.76, 0.76),
            ):
                draw.rounded_rectangle(badge_box, radius=10, fill=(235, 243, 248), outline=(126, 157, 177), width=2)
                centered_text(badge_box, exact("Model M"), badge_size, bold=False)

            self_feedback_box = region(feedback_box, 0.13, 0.60, 0.87, 0.88)
            draw.rounded_rectangle(self_feedback_box, radius=10, fill=(238, 249, 248), outline=(31, 117, 126), width=2)
            centered_text(self_feedback_box, exact("Self-Feedback"), badge_size)
            internal_start = (round((feedback_box[0] + feedback_box[2]) / 2), region(feedback_box, 0, 0.47, 1, 0.47)[1])
            internal_end = (round((self_feedback_box[0] + self_feedback_box[2]) / 2), self_feedback_box[1])
            draw_arrow_path([internal_start, internal_end], (31, 117, 126))

            iterate_box = (loop_x - round(width * 0.08), round((loop_start[1] + loop_end[1]) / 2) - 22, loop_x - 4, round((loop_start[1] + loop_end[1]) / 2) + 22)
            centered_text(iterate_box, exact("iterate"), badge_size, fill=(31, 117, 126), bold=False)
    elif semantic_dense and len(panel_boxes) >= 3:
        task_box, model_box, data_box = panel_boxes[:3]
        title_size = max(15, round(height * 0.022))
        node_size = max(13, round(height * 0.017))

        image_box = region(task_box, 0.12, 0.23, 0.88, 0.37)
        prompt_box = region(task_box, 0.12, 0.57, 0.88, 0.71)
        image_encoder_box = region(model_box, 0.06, 0.23, 0.43, 0.37)
        prompt_encoder_box = region(model_box, 0.06, 0.57, 0.43, 0.71)
        mask_decoder_box = region(model_box, 0.56, 0.38, 0.94, 0.54)
        valid_mask_box = region(model_box, 0.56, 0.69, 0.94, 0.84)
        assisted_box = region(data_box, 0.12, 0.22, 0.88, 0.34)
        semi_box = region(data_box, 0.12, 0.41, 0.88, 0.53)
        fully_box = region(data_box, 0.12, 0.60, 0.88, 0.72)
        sa1b_box = region(data_box, 0.22, 0.80, 0.78, 0.91)

        def left(box): return (box[0], (box[1] + box[3]) // 2)
        def right(box): return (box[2], (box[1] + box[3]) // 2)
        def top(box): return ((box[0] + box[2]) // 2, box[1])
        def bottom(box): return ((box[0] + box[2]) // 2, box[3])

        draw_arrow_path([right(image_box), left(image_encoder_box)], (42, 99, 161))
        draw_arrow_path([right(prompt_box), left(prompt_encoder_box)], (31, 117, 126))
        decoder_upper = (mask_decoder_box[0], round(mask_decoder_box[1] + 0.32 * (mask_decoder_box[3] - mask_decoder_box[1])))
        decoder_lower = (mask_decoder_box[0], round(mask_decoder_box[1] + 0.70 * (mask_decoder_box[3] - mask_decoder_box[1])))
        draw_arrow_path([right(image_encoder_box), decoder_upper], (42, 99, 161))
        draw_arrow_path([right(prompt_encoder_box), decoder_lower], (31, 117, 126))
        draw_arrow_path([bottom(mask_decoder_box), top(valid_mask_box)], (80, 111, 134))
        draw_arrow_path([bottom(assisted_box), top(semi_box)], (177, 92, 33))
        draw_arrow_path([bottom(semi_box), top(fully_box)], (177, 92, 33))
        draw_arrow_path([bottom(fully_box), top(sa1b_box)], (177, 92, 33))
        support_y = round(model_box[1] + 0.17 * (model_box[3] - model_box[1]))
        draw_dashed_arrow((model_box[2], support_y), (data_box[0], support_y), (177, 92, 33))

        node_specs = [
            (image_box, "Image", (237, 245, 252), (42, 99, 161)),
            (prompt_box, "Prompt", (237, 249, 247), (31, 117, 126)),
            (image_encoder_box, "Image Encoder", (237, 245, 252), (42, 99, 161)),
            (prompt_encoder_box, "Prompt Encoder", (237, 249, 247), (31, 117, 126)),
            (mask_decoder_box, "Mask Decoder", (244, 242, 251), (98, 84, 147)),
            (valid_mask_box, "Valid Segmentation Mask", (242, 248, 243), (66, 126, 80)),
            (assisted_box, "Assisted-manual", (252, 244, 235), (177, 92, 33)),
            (semi_box, "Semi-automatic", (252, 244, 235), (177, 92, 33)),
            (fully_box, "Fully Automatic", (252, 244, 235), (177, 92, 33)),
            (sa1b_box, "SA-1B", (247, 239, 229), (150, 76, 30)),
        ]
        for node_box, label, fill, outline in node_specs:
            draw.rounded_rectangle(node_box, radius=10, fill=fill, outline=outline, width=2)
            centered_text(node_box, exact(label), node_size, fill=outline)

        centered_text(region(task_box, 0.03, 0.03, 0.97, 0.15), exact("Promptable Segmentation Task"), title_size)
        centered_text(region(model_box, 0.03, 0.03, 0.97, 0.15), exact("Segment Anything Model"), title_size)
        centered_text(region(data_box, 0.03, 0.03, 0.97, 0.15), exact("Data Engine"), title_size, fill=(177, 92, 33))
    elif semantic_generic:
        node_boxes: dict[str, tuple[int, int, int, int]] = {}
        node_styles: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {}
        for node in generic_semantic_plan.get("nodes", []):
            bbox = node["bbox_percent"]
            node_box = (
                round(bbox["x"] * width),
                round(bbox["y"] * height),
                round((bbox["x"] + bbox["w"]) * width),
                round((bbox["y"] + bbox["h"]) * height),
            )
            field = str(node.get("field") or "modules")
            role = str(node.get("role") or "").casefold()
            if field == "inputs":
                fill, outline = (237, 245, 252), (42, 99, 161)
            elif field == "outputs":
                fill, outline = (242, 248, 243), (66, 126, 80)
            elif field == "innovations":
                fill, outline = (252, 244, 235), (177, 92, 33)
            elif "shared" in role or "joint" in role or "fusion" in role:
                fill, outline = (244, 242, 251), (98, 84, 147)
            else:
                fill, outline = (237, 249, 247), (31, 117, 126)
            node_boxes[node["id"]] = node_box
            node_styles[node["id"]] = (fill, outline)
            draw.rounded_rectangle(node_box, radius=max(8, round(height * 0.014)), fill=fill, outline=outline, width=3)

        relation_colors = {
            "feedback_loop": (177, 92, 33),
            "branch": (98, 84, 147),
            "conditioning": (31, 117, 126),
            "feature_flow": (42, 99, 161),
        }
        for connector in generic_semantic_plan.get("connectors", []):
            points = [(round(point[0] * width), round(point[1] * height)) for point in connector.get("path_percent", [])]
            color = relation_colors.get(str(connector.get("type") or ""), (80, 111, 134))
            draw_arrow_path(points, color)
            label = str(connector.get("label") or "").strip()
            if label and len(points) >= 2:
                middle = points[len(points) // 2]
                label_box = (middle[0] - 60, middle[1] - 18, middle[0] + 60, middle[1] + 18)
                draw.rounded_rectangle(label_box, radius=7, fill=(250, 250, 249), outline=color, width=1)
                centered_wrapped_text(label_box, label, max(11, round(height * 0.014)), fill=color, bold=False)

        for node in generic_semantic_plan.get("nodes", []):
            node_box = node_boxes[node["id"]]
            _, outline = node_styles[node["id"]]
            centered_wrapped_text(node_box, str(node.get("label") or node["id"]), max(13, round(height * 0.019)), fill=outline)
    else:
        for index in range(len(centers) - 1):
            draw_arrow_path([centers[index], centers[index + 1]])
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    semantic_label_order = []
    if semantic_feedback:
        semantic_label_order = ["input x", "Generate", "Initial Output", "FEEDBACK", "Self-Feedback", "REFINE", "Refined output", "Model M", "iterate"]
    elif semantic_dense:
        semantic_label_order = [
            "Promptable Segmentation Task", "Segment Anything Model", "Data Engine", "Image", "Prompt",
            "Image Encoder", "Prompt Encoder", "Mask Decoder", "Valid Segmentation Mask",
            "Assisted-manual", "Semi-automatic", "Fully Automatic", "SA-1B",
        ]
    elif semantic_generic:
        semantic_label_order = [str(item.get("label") or "") for item in generic_semantic_plan.get("nodes", [])]
        semantic_label_order.extend(str(item.get("label") or "") for item in generic_semantic_plan.get("connectors", []) if str(item.get("label") or "").strip())
    return {
        "summary": "Paper-semantic layout blueprint rendered from the normalized contract." if semantic_blueprint else "Content-free layout blueprint rendered from selected template.",
        "path": str(path),
        "width": width,
        "height": height,
        "aspect_ratio_decimal": round(ratio, 6),
        "template_id": profile["template_id"],
        "contains_reference_text": False,
        "contains_reference_objects": False,
        "contains_paper_semantic_labels": semantic_blueprint,
        "semantic_labels": [exact(value) for value in semantic_label_order],
        "semantic_plan": generic_semantic_plan if semantic_generic else None,
    }
