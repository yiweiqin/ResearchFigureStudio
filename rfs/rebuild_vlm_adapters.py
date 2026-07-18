from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .vlm_client import call_vlm_json, resolve_vlm_model, vlm_credentials_available


def _brief_slots(slots: list[dict]) -> list[dict]:
    return [{
        "id": item.get("id"),
        "bbox_percent": item.get("bbox_percent"),
        "paper_concept": item.get("paper_concept"),
        "display_label": item.get("display_label"),
        "semantic_role": item.get("semantic_role"),
        "asset_type": item.get("asset_type"),
    } for item in slots]


def _brief_panels(panels: list[dict]) -> list[dict]:
    return [{
        "id": item.get("id"),
        "title": item.get("title"),
        "bbox_percent": item.get("bbox_percent"),
    } for item in panels]


def _brief_controls(controls: list[dict]) -> list[dict]:
    return [{
        "id": item.get("id"),
        "source_id": item.get("source_id") or item.get("source"),
        "target_id": item.get("target_id") or item.get("target"),
        "control_kind": item.get("control_kind"),
        "path_percent": item.get("path_percent"),
        "arrowhead_direction": item.get("arrowhead_direction"),
        "stroke_color": item.get("stroke_color"),
        "stroke_width_pt": item.get("stroke_width_pt"),
        "dash_style": item.get("dash_style") or item.get("line_pattern"),
        "confidence": item.get("confidence"),
    } for item in controls]


def vlm_layout_adapter(reference_path: str | Path, base_layout: dict) -> dict:
    model = resolve_vlm_model("RFS_REBUILD_LAYOUT_MODEL", "RFS_LOCATOR_MODEL")
    prompt = f"""
You are reconstructing a diagram image as editable PowerPoint objects.
Inspect the reference image and improve the detected layout.
Only output JSON. Do not include markdown or explanations.

Use normalized bbox_percent coordinates in [0,1].
Prefer structural regions that should become editable PPT objects:
- panels: large stage/section containers
- cards: smaller editable boxes inside panels
- slots: non-text visual assets such as icons, illustrations, screenshots, tools, characters, charts
- legend_regions: legend markers or legend label areas

Rules:
- Do not create a slot for pure text, arrows, or panel borders.
- Keep ids short, stable, lowercase snake_case.
- Each slot must include id, asset_id, bbox_percent, prompt_subject if recognizable, and panel_id if inside a panel.
- Include confidence in 0..1.

Return schema:
{{
  "summary": "...",
  "confidence": 0.0,
  "panels": [{{"id":"stage_1","title":"...","bbox_percent":{{"x":0,"y":0,"w":0.1,"h":0.1}},"confidence":0.0}}],
  "cards": [{{"id":"card_1","title":"...","bbox_percent":{{"x":0,"y":0,"w":0.1,"h":0.1}},"panel_id":"stage_1","confidence":0.0}}],
  "slots": [{{"id":"slot_1","asset_id":"slot_1","bbox_percent":{{"x":0,"y":0,"w":0.1,"h":0.1}},"panel_id":"stage_1","prompt_subject":"...","confidence":0.0}}],
  "legend_regions": [{{"id":"legend_1","bbox_percent":{{"x":0,"y":0,"w":0.1,"h":0.1}},"confidence":0.0}}]
}}

Heuristic base layout:
{json.dumps(base_layout, ensure_ascii=False)}
""".strip()
    return call_vlm_json(prompt, [reference_path], model=model)


def vlm_control_adapter_factory(out_dir: str | Path) -> Callable[[str | Path, list[dict], list[dict]], dict]:
    out = Path(out_dir)

    def adapter(reference_path: str | Path, slots: list[dict], heuristic_controls: list[dict]) -> dict:
        model = resolve_vlm_model("RFS_REBUILD_CONTROL_MODEL", "RFS_CONTROL_LOCALIZER_MODEL", "RFS_LOCATOR_MODEL")
        image_paths = [reference_path]
        for overlay in [out / "reference_geometry_overlay.png", out / "reference_controls_candidates_overlay.png"]:
            if overlay.exists():
                image_paths.append(overlay)
        prompt = f"""
You are binding and refining editable PPT arrows/connectors for a diagram.
Image 1 is the original reference. Additional images may show detected layout/control overlays.
Only output JSON. Do not include markdown or explanations.

Rules:
- Preserve arrow position, direction, path shape, line width, color, and dashed/solid style from the reference.
- Use only source_id and target_id from the slot list.
- Keep path_percent as normalized [x,y] points in [0,1].
- If a line is curved, approximate with 3-6 path points.
- If source/target is uncertain, choose the most plausible objects based on arrow direction and layout.

Return schema:
{{
  "summary": "...",
  "arrows": [
    {{"id":"arrow_1","source_id":"slot_a","target_id":"slot_b","control_kind":"straight_arrow|elbow_connector|branch_connector|dashed_loop","path_percent":[[0.1,0.2],[0.3,0.2]],"arrowhead_direction":0,"stroke_color":"#333333","stroke_width_pt":1.5,"dash_style":"solid|dashed","confidence":0.0}}
  ]
}}

Slots:
{json.dumps(_brief_slots(slots), ensure_ascii=False)}

Heuristic control candidates:
{json.dumps(_brief_controls(heuristic_controls), ensure_ascii=False)}
""".strip()
        return call_vlm_json(prompt, image_paths, model=model)

    return adapter


def vlm_semantic_adapter(reference_path: str | Path, slots: list[dict], panels: list[dict], controls: list[dict], text_geometry: dict | None) -> dict:
    model = resolve_vlm_model("RFS_REBUILD_SEMANTIC_MODEL", "RFS_PROMPT_PLANNER_MODEL")
    prompt = f"""
You are planning slot-level visual assets for an editable PowerPoint rebuild.
Use the reference image plus OCR/layout/control metadata to assign semantics to each slot.
Only output JSON. Do not include markdown or explanations.

Allowed asset_type values:
character, document_stack, chart_card, tool_icon, tool_combo, device, screenshot_card, legend_marker, thin_tool, generic

Rules:
- Use nearby OCR text as the highest-priority semantic clue.
- Do not put readable text into generated image assets; text will be editable PPT text.
- prompt_subject must describe the visual subject for image generation, not the whole diagram.
- Keep ids exactly matching input slot ids.

Return schema:
{{
  "summary": "...",
  "slots": [
    {{"slot_id":"slot_1","asset_type":"character","semantic_role":"ai_critic","prompt_subject":"AI critic robot character","nearby_text":["AI Critic"]}}
  ]
}}

Panels:
{json.dumps(_brief_panels(panels), ensure_ascii=False)}

Slots:
{json.dumps(_brief_slots(slots), ensure_ascii=False)}

Controls:
{json.dumps(_brief_controls(controls), ensure_ascii=False)}

OCR text geometry:
{json.dumps(text_geometry or {}, ensure_ascii=False)}
""".strip()
    return call_vlm_json(prompt, [reference_path], model=model)


def build_rebuild_vlm_adapters(out_dir: str | Path) -> dict[str, Callable | None]:
    if not vlm_credentials_available():
        return {"layout": None, "control": None, "semantic": None}
    return {
        "layout": vlm_layout_adapter,
        "control": vlm_control_adapter_factory(out_dir),
        "semantic": vlm_semantic_adapter,
    }
