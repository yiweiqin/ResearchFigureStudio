from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from .utils import write_json


def _extract_json(text: str) -> dict:
    cleaned = text.strip().replace("```json", "```")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _ratio_value(slot: dict) -> float:
    bbox = slot.get("bbox_percent") if isinstance(slot.get("bbox_percent"), dict) else {}
    if bbox and float(bbox.get("h", 0) or 0) > 0:
        return float(bbox.get("w", 1)) / max(float(bbox.get("h", 1)), 0.001)
    ratio = str(slot.get("target_canvas_ratio") or "1:1")
    try:
        left, right = ratio.split(":", 1)
        return float(left) / max(float(right), 0.001)
    except Exception:
        return 1.0


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _shape_language(slot: dict) -> str:
    ratio = _ratio_value(slot)
    composition = str(slot.get("composition_type", "full_bleed_card"))
    if ratio < 0.45:
        shape = "very tall narrow vertical slot"
    elif ratio < 0.8:
        shape = "tall vertical card"
    elif ratio <= 1.25:
        shape = "near-square icon/card"
    elif ratio <= 2.2:
        shape = "wide horizontal card"
    else:
        shape = "very wide strip"
    if composition == "symbol_cutout":
        return f"{shape}; large symbolic object with dense reference-colored support detail"
    if composition == "scene_thumbnail":
        return f"{shape}; dense compact scene or mechanism thumbnail"
    if composition == "full_frame_icon":
        return f"{shape}; full-frame mechanism object, not a sparse standalone pictogram"
    return f"{shape}; dense full-bleed mechanism card"


def _density(slot: dict) -> str:
    area = 0.0
    bbox = slot.get("bbox_percent") if isinstance(slot.get("bbox_percent"), dict) else None
    if bbox:
        area = float(bbox.get("w", 0)) * float(bbox.get("h", 0))
    if area < 0.004:
        return "medium"
    if area < 0.012:
        return "high"
    return "very_high"


def _location(slot: dict) -> str:
    bbox = slot.get("bbox_percent") if isinstance(slot.get("bbox_percent"), dict) else {}
    x = float(bbox.get("x", 0.5))
    y = float(bbox.get("y", 0.5))
    horizontal = "left" if x < 0.33 else ("center" if x < 0.66 else "right")
    vertical = "top" if y < 0.28 else ("middle" if y < 0.66 else "bottom")
    return f"{vertical}-{horizontal} region of the reference layout"


def _slot_function(slot: dict) -> str:
    concept = str(slot.get("paper_concept") or "paper method component").strip()
    panel = str(slot.get("macro_panel") or slot.get("parent_panel") or "paper method").strip()
    metaphor = str(slot.get("visual_metaphor") or "").strip()
    must = slot.get("must_show") if isinstance(slot.get("must_show"), list) else []
    must_text = "; ".join(str(item).strip() for item in must if str(item).strip())
    if metaphor or must_text:
        return f"In panel '{panel}', visualize '{concept}' as {metaphor or 'a concrete scientific object'}; must show {must_text or 'its role in the method'}."
    return f"In panel '{panel}', visualize the paper concept '{concept}' and its role in the method."


def _is_simple_allowed(slot: dict) -> bool:
    text = " ".join(
        str(slot.get(key, ""))
        for key in ["id", "paper_concept", "macro_panel", "parent_panel", "composition_type"]
    ).lower()
    return any(term in text for term in ["legend", "badge", "label", "ocean", "openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"])


def _complexity_kind(slot: dict) -> str:
    if _is_simple_allowed(slot):
        return "legend_icon"
    composition = str(slot.get("composition_type", "full_bleed_card")).lower()
    concept = str(slot.get("paper_concept") or "").lower()
    if composition == "scene_thumbnail" or any(term in concept for term in ["setup", "scene", "participant", "screen", "camera", "interview", "video frame"]):
        return "scene_thumbnail"
    if any(term in concept for term in ["audio", "face", "pose", "text", "modality", "frame", "video"]):
        return "modality_card"
    if any(term in concept for term in ["evaluation", "benchmark", "result", "metric", "score", "questionnaire"]):
        return "result_evaluation_card"
    return "pipeline_module"


def _visual_spec_for_slot(slot: dict, style: dict, complexity_profile: str = "reference-dense") -> dict:
    kind = _complexity_kind(slot)
    concept = str(slot.get("paper_concept") or "scientific module")
    crop_objects = _merge_list(slot.get("must_show"), slot.get("reference_visual_elements")) or [concept]
    crop_objects = crop_objects[:6]
    foreground = str(slot.get("visual_metaphor") or slot.get("reference_visual_object") or crop_objects[0] or concept)
    secondary = [
        "reference-colored support surface extending close to the slot edges",
        "small contextual cue showing input-output or before-after relation",
    ]
    micro = [
        "tiny non-critical UI marks or abstract glyphs, not readable labels",
        "fine line details, shadows, separators, or texture matching the local crop",
    ]
    background = [
        "edge-to-edge local reference color field or card surface",
        "subtle scientific texture that increases fill without changing meaning",
    ]
    mechanism = "show the paper concept as a concrete local mechanism, not as a generic abstract AI icon"
    required = "dense"
    forbidden = [
        "simple icon",
        "centered icon",
        "clean blank background",
        "single object on white canvas",
        "generic blue dashboard",
        "tiny isolated pictogram",
    ]

    if kind == "legend_icon":
        required = "simple_allowed_but_full_frame"
        secondary = ["thick support shape or local colored badge surface"]
        micro = ["one small decorative non-critical mark if useful"]
        mechanism = "keep it readable as a legend/badge symbol while filling the frame"
        forbidden = ["tiny centered badge", "large blank white surround", "wrong critical letters or labels"]
    elif kind == "modality_card":
        secondary.extend(["secondary modality cue", "small processing/output cue"])
        micro.extend(["mini timeline/stream markers", "compact signal texture"])
        mechanism = "show a modality object plus at least one processing cue and one output cue"
    elif kind == "pipeline_module":
        secondary.extend(["internal subcomponent", "input/output connector cue"])
        micro.extend(["small cells, nodes, panels, or state markers", "directional process texture that is not an arrow asset"])
        mechanism = "show the internal operation of this pipeline module with layered parts"
    elif kind == "scene_thumbnail":
        secondary.extend(["environment/context object", "interaction cue"])
        micro.extend(["foreground/background depth cue", "small apparatus or interface detail"])
        mechanism = "show a compact scene with subject, environment, and process relation"
    elif kind == "result_evaluation_card":
        secondary.extend(["benchmark/task tile group", "abstract evaluation mark without fake numbers"])
        micro.extend(["tiny bars or score glyphs without readable metric values", "check/list texture"])
        mechanism = "show evaluation/result structure visually without fabricating numeric values"

    return {
        "slot_id": slot.get("id"),
        "paper_concept": slot.get("paper_concept"),
        "complexity_profile": complexity_profile,
        "complexity_kind": kind,
        "reference_crop_path": slot.get("reference_crop_path"),
        "reference_crop_objects": crop_objects,
        "foreground_subject": foreground,
        "secondary_objects": secondary[:5],
        "micro_details": micro[:5],
        "background_fill_elements": background[:4],
        "scientific_mechanism_detail": mechanism,
        "required_visual_complexity": required,
        "forbidden_simplification": forbidden,
        "object_count_target": 1 if kind == "legend_icon" else 3,
        "detail_score_target": 45 if kind == "legend_icon" else 65,
        "reference_primary_rule": "Describe and recreate the local reference crop object first; use paper concept only to adapt scientific meaning.",
    }


def build_slot_visual_spec(program: dict, style: dict, out_dir: str | Path, complexity_profile: str = "reference-dense") -> dict:
    specs = [_visual_spec_for_slot(slot, style, complexity_profile=complexity_profile) for slot in program.get("slots", [])]
    by_id = {item["slot_id"]: item for item in specs if item.get("slot_id")}
    for slot in program.get("slots", []):
        spec = by_id.get(slot.get("id"))
        if not spec:
            continue
        slot["visual_spec_id"] = f"visual_spec_{slot['id']}"
        slot["complexity_profile"] = complexity_profile
        slot["complexity_kind"] = spec["complexity_kind"]
        slot["reference_crop_objects"] = spec["reference_crop_objects"]
        slot["foreground_subject"] = spec["foreground_subject"]
        slot["secondary_objects"] = spec["secondary_objects"]
        slot["micro_details"] = spec["micro_details"]
        slot["background_fill_elements"] = spec["background_fill_elements"]
        slot["scientific_mechanism_detail"] = spec["scientific_mechanism_detail"]
        slot["required_visual_complexity"] = spec["required_visual_complexity"]
        slot["forbidden_simplification"] = spec["forbidden_simplification"]
        slot["object_count_target"] = spec["object_count_target"]
        slot["detail_score_target"] = spec["detail_score_target"]
    doc = {
        "summary": "Slot visual complexity specification created before image prompt planning.",
        "complexity_profile": complexity_profile,
        "policy": "Reference crop objects drive the visual content; non-legend slots must become dense mini scientific scenes rather than simple standalone icons.",
        "slots": specs,
    }
    write_json(Path(out_dir) / "slot_visual_spec.json", doc)
    return doc


def _heuristic_slot_plan(slot: dict, style: dict) -> dict:
    shape = _shape_language(slot)
    density = _density(slot)
    composition = str(slot.get("composition_type", "full_bleed_card"))
    visual_spec = _visual_spec_for_slot(slot, style, complexity_profile=str(slot.get("complexity_profile") or "reference-dense"))
    if composition == "symbol_cutout":
        local_style = "reference-like large symbol with thick silhouette, local colored support detail, and minimal blank surround"
    elif composition == "scene_thumbnail":
        local_style = "reference-like dense compact thumbnail; foreground subject, context objects, and edge-to-edge supporting scene detail"
    elif composition == "full_frame_icon":
        local_style = "reference-like full-frame mechanism object; not a standalone sparse pictogram; include internal detail and support elements"
    else:
        local_style = "reference-like dense scientific card; central mechanism, internal subparts, and compact process cues"
    concept = str(slot.get("paper_concept") or "reference visual object")
    metaphor = str(slot.get("visual_metaphor") or concept)
    exact_ratio = float(slot.get("aspect_ratio_decimal") or _ratio_value(slot))
    center = slot.get("center_percent") if isinstance(slot.get("center_percent"), dict) else {"x": 0.5, "y": 0.5}
    geometry_text = (
        f"exact aspect ratio {exact_ratio:.3f}:1, center x={float(center.get('x', 0.5)):.3f}, "
        f"center y={float(center.get('y', 0.5)):.3f}, width_percent={float(slot.get('width_percent', 0)):.3f}, "
        f"height_percent={float(slot.get('height_percent', 0)):.3f}"
    )
    must_show = slot.get("must_show") if isinstance(slot.get("must_show"), list) and slot.get("must_show") else [
        concept,
        "large complete reference-like object",
        "local slot shape and color cues",
    ]
    return {
        "slot_id": slot["id"],
        "paper_concept": slot.get("paper_concept"),
        "slot_function": _slot_function(slot),
        "reference_crop_path": slot.get("reference_crop_path"),
        "reference_crop_used": bool(slot.get("reference_crop_path")),
        "reference_style_profile_path": style.get("reference_style_profile_path", "reference_style_profile.json"),
        "local_color_token_ids": slot.get("local_color_token_ids", []),
        "complexity_profile": visual_spec["complexity_profile"],
        "complexity_kind": visual_spec["complexity_kind"],
        "reference_crop_objects": visual_spec["reference_crop_objects"],
        "foreground_subject": visual_spec["foreground_subject"],
        "secondary_objects": visual_spec["secondary_objects"],
        "micro_details": visual_spec["micro_details"],
        "background_fill_elements": visual_spec["background_fill_elements"],
        "scientific_mechanism_detail": visual_spec["scientific_mechanism_detail"],
        "required_visual_complexity": visual_spec["required_visual_complexity"],
        "forbidden_simplification": visual_spec["forbidden_simplification"],
        "object_count_target": visual_spec["object_count_target"],
        "detail_score_target": visual_spec["detail_score_target"],
        "reference_content_priority": "reference_primary_visual_object",
        "reference_visual_object": metaphor,
        "reference_visual_elements": must_show,
        "reference_color_palette": "inherit the local reference crop colors where visible",
        "paper_label_mapping": "use paper terminology only for editable PPT labels, not as baked image text",
        "reference_slot_role": f"{shape} in the {_location(slot)}",
        "reference_shape_language": shape,
        "reference_local_style": local_style,
        "reference_density": density,
        "reference_prompt_hint": (
            "Preserve the reference figure's rounded-card discipline, clean outlines, and readable slot density, "
            "but replace any generic UI look with the paper-specific mechanism object. "
            f"Use {geometry_text}; content fill 90-97%; empty margin below 10% on every edge."
        ),
        "visual_metaphor": metaphor,
        "must_show": must_show,
        "avoid_showing": slot.get("avoid_showing") or [],
        "image_prompt_core": (
            f"Draw a dense mini scientific scene for {metaphor} and the paper concept "
            f"{slot.get('paper_concept')}. Use this slot as a {shape}; make the object concrete, "
            f"scientific, highly detailed, and visually distinct from the other slots. "
            f"Foreground subject: {visual_spec['foreground_subject']}. Secondary objects: {'; '.join(visual_spec['secondary_objects'])}. "
            f"Micro details: {'; '.join(visual_spec['micro_details'])}. Mechanism detail: {visual_spec['scientific_mechanism_detail']}. Use {geometry_text}. "
            f"Inherit reference_style_profile {style.get('reference_style_profile_path', 'reference_style_profile.json')} "
            f"and local color token ids {slot.get('local_color_token_ids', [])}; use the saved local crop {slot.get('reference_crop_path')} as the visual object guide. "
            "Content must fill 90-97% of the canvas with empty margin below 10% on every edge. "
            "Do not add an extra white presentation tile or blank card background. Do not create a simple icon, centered icon, or single object on a clean blank canvas."
        ),
    }


def _safe_slot_filename(slot_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(slot_id)).strip("_") or "slot"


def _relative_out_path(path: Path, out_dir: str | Path) -> str:
    try:
        return str(path.relative_to(Path(out_dir))).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _crop_reference_slot(reference_path: str | Path, slot: dict, crop_dir: Path) -> Path | None:
    bbox = slot.get("bbox_percent") if isinstance(slot.get("bbox_percent"), dict) else None
    if not bbox:
        return None
    try:
        img = Image.open(reference_path).convert("RGB")
        width, height = img.size
        x = max(0.0, min(1.0, float(bbox.get("x", 0.0))))
        y = max(0.0, min(1.0, float(bbox.get("y", 0.0))))
        w = max(0.01, min(1.0, float(bbox.get("w", 1.0))))
        h = max(0.01, min(1.0, float(bbox.get("h", 1.0))))
        pad = 0.015
        left = int(max(0, (x - pad) * width))
        top = int(max(0, (y - pad) * height))
        right = int(min(width, (x + w + pad) * width))
        bottom = int(min(height, (y + h + pad) * height))
        if right <= left or bottom <= top:
            return None
        crop_dir.mkdir(parents=True, exist_ok=True)
        out = crop_dir / f"{_safe_slot_filename(slot.get('id', 'slot'))}.png"
        img.crop((left, top, right, bottom)).save(out)
        return out
    except Exception:
        return None


def _encode_image(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def _chat_completion_json(messages: list[dict[str, Any]], model: str | None = None, timeout: int = 240) -> dict:
    api_base = os.getenv("API_BASE", "").rstrip("/")
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
    model_name = model or os.getenv("RFS_PROMPT_PLANNER_MODEL") or os.getenv("MODEL_VLM") or os.getenv("MODEL_PLANNER") or "gemini-3-pro-preview-thinking"
    if not api_base or not api_key:
        raise RuntimeError("VLM prompt planner requires API_BASE and API_KEY/GEMINI_API_KEY")
    response = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps({"model": model_name, "messages": messages, "temperature": 0.18}),
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _call_vlm_prompt_plan(reference_path: str | Path, program: dict, style: dict, paper_brief: dict, model: str | None = None) -> dict:
    ref = Path(reference_path)
    b64 = _encode_image(ref)
    slots = [
        {
            "id": slot.get("id"),
            "paper_concept": slot.get("paper_concept"),
            "macro_panel": slot.get("parent_panel") or slot.get("macro_panel"),
            "slot_function": _slot_function(slot),
            "bbox_percent": slot.get("bbox_percent"),
            "center_percent": slot.get("center_percent"),
            "width_percent": slot.get("width_percent"),
            "height_percent": slot.get("height_percent"),
            "aspect_ratio_decimal": slot.get("aspect_ratio_decimal"),
            "aspect_ratio_w_h": slot.get("aspect_ratio_w_h"),
            "target_canvas_ratio": slot.get("target_canvas_ratio"),
            "target_pixels_exact": slot.get("target_pixels_exact"),
            "target_pixels": slot.get("target_pixels"),
            "generation_min_pixels": slot.get("generation_min_pixels"),
            "composition_type": slot.get("composition_type"),
            "visual_metaphor": slot.get("visual_metaphor"),
            "must_show": slot.get("must_show"),
            "avoid_showing": slot.get("avoid_showing"),
            "reference_crop_path": slot.get("reference_crop_path"),
            "local_color_token_ids": slot.get("local_color_token_ids"),
            "complexity_profile": slot.get("complexity_profile"),
            "complexity_kind": slot.get("complexity_kind"),
            "reference_crop_objects": slot.get("reference_crop_objects"),
            "foreground_subject": slot.get("foreground_subject"),
            "secondary_objects": slot.get("secondary_objects"),
            "micro_details": slot.get("micro_details"),
            "background_fill_elements": slot.get("background_fill_elements"),
            "scientific_mechanism_detail": slot.get("scientific_mechanism_detail"),
            "required_visual_complexity": slot.get("required_visual_complexity"),
            "forbidden_simplification": slot.get("forbidden_simplification"),
            "object_count_target": slot.get("object_count_target"),
            "detail_score_target": slot.get("detail_score_target"),
            "reference_style_profile_path": style.get("reference_style_profile_path", "reference_style_profile.json"),
        }
        for slot in program.get("slots", [])
    ]
    prompt = f"""
You are a reference-image-aware prompt planner for image-rich scientific figures.
Inspect the reference image and the slot list. Return only JSON.

Task:
- For each slot, write a local visual prompt plan that binds the paper concept to the reference image's local slot style.
- Do not generate final image prompts. Do not write code.
- Do not change scientific content. The paper remains the source of truth.
- Avoid generic blue sci-fi dashboards. Each slot needs a distinct scientific silhouette.
- Except explicit legend/badge slots, do not plan a simple icon. Plan a dense mini scientific scene/card with layered local objects.
- Every normal slot must preserve the slot_visual_spec fields: foreground subject, 2-5 secondary objects, micro details, background fill elements, and mechanism detail.
- For every slot, output an image_prompt_core that the image generator can use
  directly. It must mention concrete visible objects, not just abstract labels.
- For every slot, image_prompt_core must include its exact decimal aspect ratio,
  center point, width/height percent, content fill 90-97%, and empty margin below
  10% on every edge. Do not request extra white presentation tiles.

Return schema:
{{
  "summary": "Reference-aware slot prompt plan.",
  "mode": "vlm",
  "slots": [
    {{
      "slot_id": "input slot id",
      "paper_concept": "...",
      "slot_function": "what this block does in the figure, grounded in the paper",
      "reference_slot_role": "what this location/shape is doing in the reference layout",
      "reference_shape_language": "tall card|wide card|square icon|small badge|strip plus local shape notes",
      "reference_local_style": "local border, density, icon/card treatment, background, and visual rhythm",
      "reference_density": "low|medium|high|very_high",
      "complexity_kind": "legend_icon|modality_card|pipeline_module|scene_thumbnail|result_evaluation_card",
      "foreground_subject": "dominant object from local crop",
      "secondary_objects": ["2-5 secondary objects for non-legend slots"],
      "micro_details": ["2-5 small non-critical details that increase density"],
      "background_fill_elements": ["edge-to-edge support details"],
      "scientific_mechanism_detail": "how this slot visibly shows the paper concept",
      "required_visual_complexity": "simple_allowed_but_full_frame|dense|very_dense",
      "forbidden_simplification": ["simple icon", "centered icon", "blank background"],
      "reference_prompt_hint": "one sentence telling the image generator how to match this local slot while drawing the paper concept",
      "visual_metaphor": "concrete object to draw; improve if input metaphor is too generic",
      "must_show": ["2-5 concrete paper-specific visible objects/relations"],
      "avoid_showing": ["generic or scientifically wrong visuals to avoid"],
      "image_prompt_core": "2-4 sentence direct prompt core for this slot image; describe the actual object/scene/mechanism to draw"
    }}
  ],
  "warnings": []
}}

Paper title: {paper_brief.get("title_guess")}
Figure goal: {paper_brief.get("figure_goal")}
Style sheet:
{json.dumps(style, ensure_ascii=False)}
Slots:
{json.dumps(slots, ensure_ascii=False)}
""".strip()
    return _chat_completion_json(
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        model=model,
        timeout=240,
    )


def _call_vlm_slot_prompt_plan(
    reference_path: str | Path,
    slot_crop_path: Path | None,
    slot: dict,
    style: dict,
    paper_brief: dict,
    model: str | None = None,
) -> dict:
    ref_b64 = _encode_image(reference_path)
    content: list[dict[str, Any]] = []
    prompt = f"""
You are designing exactly one small image block prompt for a complex editable AI/ML research figure.
Return only JSON. Do not write markdown.

Reference-primary task:
- The reference image is the primary source for visual objects, local composition,
  local color, icon/card shape, and what this slot should visibly look like.
- The paper is used to confirm terminology, module names, and scientific labels,
  but those labels will be added later as editable PowerPoint text.
- Do not replace a reference slot object with an abstract paper-internal object
  unless the reference object is scientifically impossible.
- If the local crop shows a monitor, video strip, microphone, waveform, face
  card, pose skeleton, clock, clipboard, database, participant, camera, document,
  modality card, or OCEAN badge, the image prompt must recreate that object.
- This slot already has a slot_visual_spec. Use it as a hard contract, not optional advice.
- Except explicit legend/badge slots, the prompt must describe a dense mini scientific scene/card with 2-5 layered objects, micro-details, and edge-to-edge support detail. Do not plan a simple standalone icon.

Use the full reference image for global style and the local crop for this slot's actual content, shape, density, and color.

Slot:
{json.dumps({
    "id": slot.get("id"),
    "paper_concept": slot.get("paper_concept"),
    "macro_panel": slot.get("parent_panel") or slot.get("macro_panel"),
    "slot_function": _slot_function(slot),
    "bbox_percent": slot.get("bbox_percent"),
    "center_percent": slot.get("center_percent"),
    "width_percent": slot.get("width_percent"),
    "height_percent": slot.get("height_percent"),
    "aspect_ratio_decimal": slot.get("aspect_ratio_decimal"),
    "aspect_ratio_w_h": slot.get("aspect_ratio_w_h"),
    "target_canvas_ratio": slot.get("target_canvas_ratio"),
    "target_pixels_exact": slot.get("target_pixels_exact"),
    "target_pixels": slot.get("target_pixels"),
    "generation_min_pixels": slot.get("generation_min_pixels"),
    "composition_type": slot.get("composition_type"),
    "visual_metaphor": slot.get("visual_metaphor"),
    "must_show": slot.get("must_show"),
    "avoid_showing": slot.get("avoid_showing"),
    "text_policy": slot.get("text_policy"),
    "target_content_fill_percent": slot.get("target_content_fill_percent"),
    "min_content_fill_percent": slot.get("min_content_fill_percent"),
    "max_empty_margin_percent": slot.get("max_empty_margin_percent"),
    "reference_crop_path": slot.get("reference_crop_path"),
    "local_color_token_ids": slot.get("local_color_token_ids"),
    "visual_spec_id": slot.get("visual_spec_id"),
    "complexity_profile": slot.get("complexity_profile"),
    "complexity_kind": slot.get("complexity_kind"),
    "reference_crop_objects": slot.get("reference_crop_objects"),
    "foreground_subject": slot.get("foreground_subject"),
    "secondary_objects": slot.get("secondary_objects"),
    "micro_details": slot.get("micro_details"),
    "background_fill_elements": slot.get("background_fill_elements"),
    "scientific_mechanism_detail": slot.get("scientific_mechanism_detail"),
    "required_visual_complexity": slot.get("required_visual_complexity"),
    "forbidden_simplification": slot.get("forbidden_simplification"),
    "object_count_target": slot.get("object_count_target"),
    "detail_score_target": slot.get("detail_score_target"),
    "reference_style_profile_path": style.get("reference_style_profile_path", "reference_style_profile.json"),
}, ensure_ascii=False)}

Paper title: {paper_brief.get("title_guess")}
Figure goal: {paper_brief.get("figure_goal")}
Style sheet: {json.dumps(style, ensure_ascii=False)}

Output schema:
{{
  "slot_id": "{slot.get('id')}",
  "paper_concept": "...",
  "slot_function": "what this block does in the figure",
  "reference_content_priority": "reference_primary_visual_object",
  "reference_visual_object": "the concrete object actually visible in the local reference crop",
  "reference_visual_elements": ["3-6 visible elements from the reference crop to recreate"],
  "reference_color_palette": "local colors from the crop, such as blue video, orange frame, purple face card, teal database, etc.",
  "paper_label_mapping": "how this reference object maps to the paper concept; labels remain editable in PPT",
  "reference_slot_role": "local role of this slot in the reference image",
  "reference_shape_language": "slot shape, border/card/icon treatment, aspect-ratio language",
  "reference_local_style": "local color, density, line, shadow, background, visual rhythm",
  "reference_density": "low|medium|high|very_high",
  "complexity_profile": "{slot.get('complexity_profile') or 'reference-dense'}",
  "complexity_kind": "{slot.get('complexity_kind') or 'pipeline_module'}",
  "reference_crop_objects": ["objects actually visible in the local crop"],
  "foreground_subject": "dominant local crop object to draw large",
  "secondary_objects": ["2-5 supporting objects for non-legend slots"],
  "micro_details": ["2-5 small non-critical details that increase visual density"],
  "background_fill_elements": ["edge-to-edge support details from the local reference style"],
  "scientific_mechanism_detail": "visible mechanism relation adapted from the paper concept",
  "required_visual_complexity": "simple_allowed_but_full_frame|dense|very_dense",
  "forbidden_simplification": ["simple icon", "centered icon", "clean blank background", "single object on white canvas"],
  "reference_prompt_hint": "one sentence binding local reference style to the paper concept",
  "visual_metaphor": "concrete visible object/scene/mechanism to draw",
  "must_show": ["3-6 concrete visible elements or relations from the paper concept"],
  "avoid_showing": ["generic or scientifically wrong visuals to avoid"],
  "image_prompt_core": "A direct image-generation prompt core for this slot. It must primarily recreate the local reference object's content, shape, and colors, adapted only enough to match the paper concept. No critical labels, equations, metrics, or fake axes."
}}

Important:
- Treat the local reference crop as a visual input for this slot, not optional context.
- Explicitly inherit the global reference_style_profile and the slot's local color token ids.
- Do not use generic blue technology dashboard language.
- Do not describe only an abstract module name.
- Prefer concrete visible reference objects from the crop over abstract paper-internal metaphors.
- Preserve local color variety from the reference figure instead of forcing every block into one blue-green palette.
- The image_prompt_core must explicitly mention the exact decimal aspect ratio, the slot center, the slot width/height percent, useful content fill 90-97%, and empty margin below 10% on every edge.
- The image_prompt_core must explicitly mention the foreground subject, secondary objects, micro details, background fill elements, and scientific mechanism detail from slot_visual_spec.
- For non-legend slots, the image_prompt_core must include "dense mini scientific scene/card", "2-5 layered objects", "edge-to-edge supporting detail", and "not a standalone pictogram".
- Do not ask for a white presentation tile, white mat, large white card, or generic blank canvas unless the local crop truly contains that object.
- Keep prompt core suitable for a small slot image; arrows and critical text will be added in PPT.
""".strip()
    content.append({"type": "text", "text": prompt})
    content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref_b64}"}})
    if slot_crop_path and slot_crop_path.exists():
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_encode_image(slot_crop_path)}"}})
    return _chat_completion_json([{"role": "user", "content": content}], model=model, timeout=180)


def _call_vlm_prompt_plan_per_slot(
    reference_path: str | Path,
    program: dict,
    style: dict,
    paper_brief: dict,
    out_dir: str | Path,
    model: str | None = None,
    workers: int | None = None,
) -> dict:
    out = Path(out_dir)
    crop_dir = out / "reference_slot_crops"
    slots = program.get("slots", [])
    worker_count = max(1, min(12, int(workers or os.getenv("RFS_PROMPT_PLAN_WORKERS") or 4)))
    planned_by_id: dict[str, dict] = {}
    warnings = []

    def plan_one(slot: dict) -> tuple[str, dict, str | None]:
        slot_id = str(slot.get("id"))
        rel_crop = str(slot.get("reference_crop_path") or "").strip()
        crop_path = (out / rel_crop) if rel_crop else _crop_reference_slot(reference_path, slot, crop_dir)
        if crop_path and crop_path.exists():
            slot["reference_crop_path"] = _relative_out_path(crop_path, out)
        max_attempts = max(1, min(5, int(os.getenv("RFS_PROMPT_PLAN_RETRIES", "2")) + 1))
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                item = _call_vlm_slot_prompt_plan(reference_path, crop_path, slot, style, paper_brief, model=model)
                item["prompt_plan_source"] = "vlm_per_slot"
                item["prompt_plan_attempt"] = attempt
                item["reference_crop_path"] = slot.get("reference_crop_path")
                item["reference_crop_used"] = bool(crop_path and crop_path.exists())
                item["reference_style_profile_path"] = style.get("reference_style_profile_path", "reference_style_profile.json")
                item["local_color_token_ids"] = slot.get("local_color_token_ids", [])
                return slot_id, item, None
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts:
                    time.sleep(min(20.0, 1.5 * (2 ** (attempt - 1))))
        if not _bool_env("RFS_ALLOW_PROMPT_PLAN_FALLBACK", True):
            raise RuntimeError(f"VLM slot prompt planning failed for slot {slot.get('id')}: {last_exc}") from last_exc
        fallback = _heuristic_slot_plan(slot, style)
        fallback["prompt_plan_source"] = "reference_primary_heuristic_after_vlm_failure"
        fallback["prompt_plan_attempt"] = max_attempts
        fallback["reference_crop_path"] = slot.get("reference_crop_path")
        fallback["reference_crop_used"] = bool(crop_path and crop_path.exists())
        fallback["reference_style_profile_path"] = style.get("reference_style_profile_path", "reference_style_profile.json")
        fallback["local_color_token_ids"] = slot.get("local_color_token_ids", [])
        return slot_id, fallback, f"{slot.get('id')}: {last_exc}"

    if worker_count == 1 or len(slots) <= 1:
        for slot in slots:
            slot_id, item, warning = plan_one(slot)
            planned_by_id[slot_id] = item
            if warning:
                warnings.append(warning)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(plan_one, slot): slot for slot in slots}
            for future in as_completed(futures):
                slot_id, item, warning = future.result()
                planned_by_id[slot_id] = item
                if warning:
                    warnings.append(warning)

    planned = [planned_by_id[str(slot.get("id"))] for slot in slots if str(slot.get("id")) in planned_by_id]
    return {
        "summary": "Per-slot VLM prompt plan generated from paper concepts, full reference image, and local reference crops.",
        "mode": "vlm_per_slot_parallel" if worker_count > 1 else "vlm_per_slot",
        "prompt_plan_workers": worker_count,
        "slots": planned,
        "warnings": warnings,
    }


def _merge_list(base, extra) -> list[str]:
    result: list[str] = []
    for item in (base if isinstance(base, list) else []):
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    for item in (extra if isinstance(extra, list) else []):
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result[:8]


def _contract_prompt_core(core: str, item: dict, slot: dict, style: dict) -> str:
    text = str(core or "").strip()
    style_path = str(item.get("reference_style_profile_path") or slot.get("reference_style_profile_path") or style.get("reference_style_profile_path", "reference_style_profile.json"))
    crop_path = str(item.get("reference_crop_path") or slot.get("reference_crop_path") or "")
    token_ids = item.get("local_color_token_ids") if isinstance(item.get("local_color_token_ids"), list) else slot.get("local_color_token_ids", [])
    center = slot.get("center_percent") if isinstance(slot.get("center_percent"), dict) else {"x": 0.5, "y": 0.5}
    complexity_kind = str(item.get("complexity_kind") or slot.get("complexity_kind") or "pipeline_module")
    foreground = str(item.get("foreground_subject") or slot.get("foreground_subject") or slot.get("visual_metaphor") or slot.get("paper_concept") or "reference object")
    secondary = _merge_list(item.get("secondary_objects"), slot.get("secondary_objects"))
    micro = _merge_list(item.get("micro_details"), slot.get("micro_details"))
    background = _merge_list(item.get("background_fill_elements"), slot.get("background_fill_elements"))
    mechanism = str(item.get("scientific_mechanism_detail") or slot.get("scientific_mechanism_detail") or "show the paper concept as a concrete visual mechanism")
    dense_clause = ""
    if complexity_kind != "legend_icon":
        dense_clause = (
            " This must be a dense mini scientific scene/card with 2-5 layered objects, edge-to-edge supporting detail, and not a standalone pictogram. "
            "Do not create a simple icon, centered icon, clean blank background, single object on white canvas, generic dashboard, or tiny isolated pictogram. "
        )
    required = (
        f" Use {style_path} as reference_style_profile and use local reference crop {crop_path} as the primary visual grounding. "
        f"Inherit local color token ids {token_ids}. "
        f"Slot visual spec: complexity_kind={complexity_kind}; foreground_subject={foreground}; "
        f"secondary_objects={secondary}; micro_details={micro}; background_fill_elements={background}; scientific_mechanism_detail={mechanism}. "
        f"Exact geometry: aspect ratio {slot.get('aspect_ratio_decimal')}:1, center x={float(center.get('x', 0.5)):.3f}, "
        f"center y={float(center.get('y', 0.5)):.3f}, width_percent={float(slot.get('width_percent', 0)):.3f}, "
        f"height_percent={float(slot.get('height_percent', 0)):.3f}. "
        "Useful visual content must fill 90-97% of the canvas, and empty margin must stay below 10% on every edge. "
        "Recreate the local crop object's shape, density, and color rhythm first; paper terms only adapt the scientific mapping."
        f"{dense_clause}"
    )
    lowered = text.lower()
    missing_density = complexity_kind != "legend_icon" and ("dense mini scientific" not in lowered or "2-5" not in lowered or "standalone pictogram" not in lowered)
    if "reference_style_profile" not in lowered or "crop" not in lowered or "90-97" not in lowered or "10%" not in lowered or "foreground_subject" not in lowered or missing_density:
        text = f"{text.rstrip()} {required}".strip()
    return text


def _normalize_plan(raw: dict, program: dict, style: dict, mode: str) -> dict:
    raw_slots = raw.get("slots", []) if isinstance(raw.get("slots"), list) else []
    by_id = {str(item.get("slot_id")): item for item in raw_slots if isinstance(item, dict) and item.get("slot_id")}
    planned = []
    for slot in program.get("slots", []):
        item = by_id.get(slot["id"]) or _heuristic_slot_plan(slot, style)
        fallback = _heuristic_slot_plan(slot, style)
        core = _contract_prompt_core(str(item.get("image_prompt_core") or fallback["image_prompt_core"]), item, slot, style)
        planned.append({
            "slot_id": slot["id"],
            "paper_concept": slot.get("paper_concept"),
            "bbox_percent": slot.get("bbox_percent"),
            "center_percent": slot.get("center_percent"),
            "width_percent": slot.get("width_percent"),
            "height_percent": slot.get("height_percent"),
            "aspect_ratio_decimal": slot.get("aspect_ratio_decimal"),
            "aspect_ratio_w_h": slot.get("aspect_ratio_w_h"),
            "target_canvas_ratio": slot.get("target_canvas_ratio"),
            "target_pixels_exact": slot.get("target_pixels_exact"),
            "target_pixels": slot.get("target_pixels"),
            "generation_min_pixels": slot.get("generation_min_pixels"),
            "target_content_fill_percent": slot.get("target_content_fill_percent"),
            "min_content_fill_percent": slot.get("min_content_fill_percent"),
            "max_empty_margin_percent": slot.get("max_empty_margin_percent"),
            "reference_crop_path": str(item.get("reference_crop_path") or slot.get("reference_crop_path") or ""),
            "reference_crop_used": bool(item.get("reference_crop_used") or slot.get("reference_crop_path")),
            "reference_style_profile_path": str(item.get("reference_style_profile_path") or slot.get("reference_style_profile_path") or style.get("reference_style_profile_path", "reference_style_profile.json")),
            "local_color_token_ids": item.get("local_color_token_ids") if isinstance(item.get("local_color_token_ids"), list) else slot.get("local_color_token_ids", []),
            "visual_spec_id": slot.get("visual_spec_id") or f"visual_spec_{slot['id']}",
            "complexity_profile": str(item.get("complexity_profile") or slot.get("complexity_profile") or "reference-dense"),
            "complexity_kind": str(item.get("complexity_kind") or slot.get("complexity_kind") or "pipeline_module"),
            "reference_crop_objects": _merge_list(item.get("reference_crop_objects"), slot.get("reference_crop_objects")),
            "foreground_subject": str(item.get("foreground_subject") or slot.get("foreground_subject") or fallback.get("foreground_subject", "")),
            "secondary_objects": _merge_list(item.get("secondary_objects"), slot.get("secondary_objects")),
            "micro_details": _merge_list(item.get("micro_details"), slot.get("micro_details")),
            "background_fill_elements": _merge_list(item.get("background_fill_elements"), slot.get("background_fill_elements")),
            "scientific_mechanism_detail": str(item.get("scientific_mechanism_detail") or slot.get("scientific_mechanism_detail") or fallback.get("scientific_mechanism_detail", "")),
            "required_visual_complexity": str(item.get("required_visual_complexity") or slot.get("required_visual_complexity") or "dense"),
            "forbidden_simplification": _merge_list(item.get("forbidden_simplification"), slot.get("forbidden_simplification")),
            "object_count_target": int(item.get("object_count_target") or slot.get("object_count_target") or 3),
            "detail_score_target": int(item.get("detail_score_target") or slot.get("detail_score_target") or 65),
            "prompt_plan_source": str(item.get("prompt_plan_source") or "unknown"),
            "prompt_plan_attempt": item.get("prompt_plan_attempt"),
            "slot_function": str(item.get("slot_function") or fallback["slot_function"]),
            "reference_content_priority": str(item.get("reference_content_priority") or fallback["reference_content_priority"]),
            "reference_visual_object": str(item.get("reference_visual_object") or fallback["reference_visual_object"]),
            "reference_visual_elements": _merge_list(item.get("reference_visual_elements"), fallback.get("reference_visual_elements")),
            "reference_color_palette": str(item.get("reference_color_palette") or fallback["reference_color_palette"]),
            "paper_label_mapping": str(item.get("paper_label_mapping") or fallback["paper_label_mapping"]),
            "reference_slot_role": str(item.get("reference_slot_role") or fallback["reference_slot_role"]),
            "reference_shape_language": str(item.get("reference_shape_language") or fallback["reference_shape_language"]),
            "reference_local_style": str(item.get("reference_local_style") or fallback["reference_local_style"]),
            "reference_density": str(item.get("reference_density") or fallback["reference_density"]),
            "reference_prompt_hint": str(item.get("reference_prompt_hint") or fallback["reference_prompt_hint"]),
            "visual_metaphor": str(item.get("visual_metaphor") or slot.get("visual_metaphor") or fallback["visual_metaphor"]),
            "must_show": _merge_list(slot.get("must_show"), item.get("must_show") or fallback.get("must_show")),
            "avoid_showing": _merge_list(slot.get("avoid_showing"), item.get("avoid_showing") or fallback.get("avoid_showing")),
            "image_prompt_core": core,
        })
    return {
        "summary": raw.get("summary") or "Reference-aware slot prompt plan generated before image prompts.",
        "mode": raw.get("mode") or mode,
        "prompt_plan_workers": raw.get("prompt_plan_workers"),
        "slots": planned,
        "warnings": raw.get("warnings", []) if isinstance(raw.get("warnings"), list) else [],
    }


def apply_slot_prompt_plan(program: dict, plan: dict) -> dict:
    by_id = {item["slot_id"]: item for item in plan.get("slots", []) if isinstance(item, dict) and item.get("slot_id")}
    for slot in program.get("slots", []):
        item = by_id.get(slot.get("id"))
        if not item:
            continue
        slot["prompt_plan_id"] = f"prompt_plan_{slot['id']}"
        for key in [
            "slot_function",
            "reference_content_priority",
            "reference_visual_object",
            "reference_color_palette",
            "paper_label_mapping",
            "reference_slot_role",
            "reference_shape_language",
            "reference_local_style",
            "reference_density",
            "reference_prompt_hint",
            "reference_crop_path",
            "reference_style_profile_path",
            "visual_spec_id",
            "complexity_profile",
            "complexity_kind",
            "foreground_subject",
            "scientific_mechanism_detail",
            "required_visual_complexity",
            "visual_metaphor",
            "image_prompt_core",
        ]:
            if item.get(key):
                slot[key] = item[key]
        if isinstance(item.get("local_color_token_ids"), list):
            slot["local_color_token_ids"] = item["local_color_token_ids"]
        for key in [
            "reference_crop_objects",
            "secondary_objects",
            "micro_details",
            "background_fill_elements",
            "forbidden_simplification",
        ]:
            if isinstance(item.get(key), list):
                slot[key] = _merge_list(slot.get(key), item.get(key))
        for key in ["object_count_target", "detail_score_target"]:
            if item.get(key) is not None:
                slot[key] = item[key]
        slot["must_show"] = _merge_list(slot.get("must_show"), item.get("must_show"))
        slot["avoid_showing"] = _merge_list(slot.get("avoid_showing"), item.get("avoid_showing"))
        slot["reference_visual_elements"] = _merge_list(slot.get("reference_visual_elements"), item.get("reference_visual_elements"))
    slots_by_id = {slot.get("id"): slot for slot in program.get("slots", [])}
    for asset in program.get("assets", []):
        slot = slots_by_id.get(asset.get("slot_id"))
        if not slot:
            continue
        asset["reference_crop_path"] = slot.get("reference_crop_path")
        asset["local_color_token_ids"] = slot.get("local_color_token_ids", [])
        asset["visual_spec_id"] = slot.get("visual_spec_id")
        asset["complexity_kind"] = slot.get("complexity_kind")
        asset["required_visual_complexity"] = slot.get("required_visual_complexity")
        asset["style_profile_path"] = slot.get("reference_style_profile_path") or program.get("style", {}).get("reference_style_profile_path", "reference_style_profile.json")
    return program


def plan_slot_prompts(
    reference_path: str | Path,
    paper_brief: dict,
    inventory: dict,
    style: dict,
    out_dir: str | Path,
    program: dict,
    mode: str = "vlm",
    model: str | None = None,
    workers: int | None = None,
    complexity_profile: str = "reference-dense",
) -> tuple[dict, dict]:
    out = Path(out_dir)
    crop_dir = out / "reference_slot_crops"
    for slot in program.get("slots", []):
        crop_path = _crop_reference_slot(reference_path, slot, crop_dir)
        if crop_path:
            rel_crop = _relative_out_path(crop_path, out)
            slot["reference_crop_path"] = rel_crop
            slot["reference_crop_policy"] = "tight_slot_crop_with_minimal_context"
            slot["reference_style_profile_path"] = style.get("reference_style_profile_path", "reference_style_profile.json")
    _visual_spec = build_slot_visual_spec(program, style, out, complexity_profile=complexity_profile)
    write_json(out / "figure_program.json", program)
    briefing = {
        "summary": "Reference slot prompt briefing sent to the prompt planner before image generation.",
        "mode": mode,
        "prompt_plan_workers": max(1, min(12, int(workers or os.getenv("RFS_PROMPT_PLAN_WORKERS") or 4))) if mode == "vlm" else 0,
        "slot_visual_spec_path": "slot_visual_spec.json",
        "complexity_profile": complexity_profile,
        "slots": [
            {
                "slot_id": slot.get("id"),
                "paper_concept": slot.get("paper_concept"),
                "slot_function": _slot_function(slot),
                "bbox_percent": slot.get("bbox_percent"),
                "center_percent": slot.get("center_percent"),
                "width_percent": slot.get("width_percent"),
                "height_percent": slot.get("height_percent"),
                "aspect_ratio_decimal": slot.get("aspect_ratio_decimal"),
                "aspect_ratio_w_h": slot.get("aspect_ratio_w_h"),
                "target_canvas_ratio": slot.get("target_canvas_ratio"),
                "target_pixels_exact": slot.get("target_pixels_exact"),
                "target_pixels": slot.get("target_pixels"),
                "generation_min_pixels": slot.get("generation_min_pixels"),
                "composition_type": slot.get("composition_type"),
                "visual_metaphor": slot.get("visual_metaphor"),
                "must_show": slot.get("must_show"),
                "avoid_showing": slot.get("avoid_showing"),
                "reference_crop_path": slot.get("reference_crop_path"),
                "reference_crop_policy": slot.get("reference_crop_policy"),
                "local_color_token_ids": slot.get("local_color_token_ids"),
                "reference_style_profile_path": slot.get("reference_style_profile_path"),
                "visual_spec_id": slot.get("visual_spec_id"),
                "complexity_profile": slot.get("complexity_profile"),
                "complexity_kind": slot.get("complexity_kind"),
                "reference_crop_objects": slot.get("reference_crop_objects"),
                "foreground_subject": slot.get("foreground_subject"),
                "secondary_objects": slot.get("secondary_objects"),
                "micro_details": slot.get("micro_details"),
                "background_fill_elements": slot.get("background_fill_elements"),
                "scientific_mechanism_detail": slot.get("scientific_mechanism_detail"),
                "required_visual_complexity": slot.get("required_visual_complexity"),
                "forbidden_simplification": slot.get("forbidden_simplification"),
                "object_count_target": slot.get("object_count_target"),
                "detail_score_target": slot.get("detail_score_target"),
            }
            for slot in program.get("slots", [])
        ],
    }
    write_json(out / "reference_slot_prompt_brief.json", briefing)
    if mode == "vlm":
        raw = _call_vlm_prompt_plan_per_slot(reference_path, program, style, paper_brief, out, model=model, workers=workers)
        plan = _normalize_plan(raw, program, style, mode="vlm_per_slot")
    elif mode == "vlm-batch":
        raw = _call_vlm_prompt_plan(reference_path, program, style, paper_brief, model=model)
        plan = _normalize_plan(raw, program, style, mode="vlm_batch")
    else:
        plan = _normalize_plan({"summary": "Heuristic reference-aware slot prompt plan.", "mode": "heuristic"}, program, style, mode="heuristic")
    write_json(out / "slot_prompt_plan.json", plan)
    updated_program = apply_slot_prompt_plan(program, plan)
    write_json(out / "figure_program.json", updated_program)
    return plan, updated_program
