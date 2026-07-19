from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from .professional_dsl import fallback_professional_dsl
from .vlm_client import call_vlm_json, resolve_vlm_model, vlm_credentials_available


PROFESSIONAL_REBUILD_EXPERIENCE = """
High-quality one-off rebuild scripts in this project follow this pattern:
1. Define canvas pixel size and PowerPoint inch mapping first.
2. Create role-based text style tokens instead of ad-hoc font settings.
3. Place all visible titles, labels, callouts, legends, and captions as editable text boxes.
4. Use explicit panel/card/slot coordinates, not only inferred center-to-center layout.
5. Record arrows and dashed loops as explicit path points before PPT rendering.
6. Treat complex illustrations as slot-level image assets with specific prompts, local background colors, and aspect-ratio-aware generation.
7. Never place the whole reference figure as the final slide background.
Priority order: structure similarity, text accuracy, arrow/path accuracy, then asset beauty.
""".strip()


PROFESSIONAL_DSL_FEWSHOT = {
    "summary": "Three-stage architecture figure reconstructed as controlled DSL.",
    "dsl_version": "1.0",
    "planner": {"mode": "few_shot_example", "layout_pattern": "three_stage_horizontal_architecture"},
    "canvas": {"width_px": 1770, "height_px": 975, "width_in": 15.6, "height_in": 8.594, "background": "#F3F1EC"},
    "objects": [
        {"type": "canvas", "id": "canvas", "width_px": 1770, "height_px": 975, "width_in": 15.6, "height_in": 8.594, "background": "#F3F1EC"},
        {"type": "style_tokens", "id": "style_tokens", "font_family": "Arial", "text_size_scale": 1.08, "palette": ["#F3F1EC", "#8AA4BC", "#E1A45D", "#84A57F"]},
        {"type": "text", "id": "title", "text": "AutoFigure Architecture", "bbox_percent": {"x": 0.028, "y": 0.046, "w": 0.35, "h": 0.062}, "font_size_pt": 23, "bold": True, "align": "left"},
        {"type": "panel", "id": "stage_1", "title": "Stage I: Concept Extraction", "bbox_percent": {"x": 0.024, "y": 0.174, "w": 0.305, "h": 0.667}, "fill_color": "#EAF3FF", "stroke_color": "#8AA4BC"},
        {"type": "asset_slot", "id": "vlm_agent_robot", "asset_id": "vlm_agent_robot", "bbox_percent": {"x": 0.161, "y": 0.258, "w": 0.093, "h": 0.164}, "asset_type": "character", "prompt_subject": "cute robot assistant head", "background_color_hex": "#EAF3FF", "generation_aspect_ratio": "9:16", "content_fill_target": 0.88},
        {"type": "text", "id": "vlm_agent_label", "text": "VLM Agent", "bbox_percent": {"x": 0.175, "y": 0.432, "w": 0.067, "h": 0.027}, "font_size_pt": 10.5, "bold": True},
        {"type": "polyline", "id": "input_to_vlm", "source_id": "input_text_stack", "target_id": "vlm_agent_robot", "path_percent": [[0.125, 0.355], [0.157, 0.355]], "stroke_color": "#607998", "stroke_width_pt": 2.5},
        {"type": "dashed_loop", "id": "critique_refinement_loop", "source_id": "ai_critic", "target_id": "ai_designer", "path_percent": [[0.43, 0.35], [0.60, 0.35], [0.61, 0.73], [0.44, 0.73], [0.43, 0.35]], "stroke_color": "#D99045", "stroke_width_pt": 2.0, "dash_style": "dashed"},
    ],
}


def _brief_program(program: dict[str, Any]) -> dict[str, Any]:
    return {
        "canvas": program.get("canvas"),
        "panels": program.get("panels", []),
        "cards": program.get("cards", []),
        "slots": program.get("slots", []),
        "arrows": program.get("arrows", []),
        "text_program": program.get("text_program", {}),
    }


def plan_professional_dsl(
    reference_path: str | Path,
    baseline_program: dict[str, Any],
    text_geometry: dict[str, Any] | None,
    planner_adapter: Callable[[str | Path, dict[str, Any], dict[str, Any] | None], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if planner_adapter:
        try:
            dsl = planner_adapter(reference_path, baseline_program, text_geometry)
            dsl.setdefault("planner", {})
            dsl["planner"].update({"mode": "adapter", "vlm_status": "used"})
            return dsl, {"status": "used", "mode": "adapter"}
        except Exception as exc:
            fallback = fallback_professional_dsl(reference_path, baseline_program, baseline_program.get("text_program"))
            fallback["planner"] = {"mode": "fallback_after_adapter_error", "vlm_status": "fallback", "error": str(exc)}
            return fallback, {"status": "fallback", "mode": "fallback_after_adapter_error", "error": str(exc)}

    if not vlm_credentials_available():
        fallback = fallback_professional_dsl(reference_path, baseline_program, baseline_program.get("text_program"))
        fallback["planner"] = {"mode": "fallback_no_vlm_credentials", "vlm_status": "fallback"}
        return fallback, {"status": "fallback", "mode": "fallback_no_vlm_credentials"}

    model = resolve_vlm_model("RFS_PROFESSIONAL_REBUILD_MODEL", "MODEL_VLM")
    prompt = f"""
You are generating a controlled Figure DSL for rebuilding a diagram as editable PowerPoint.
Only output JSON. Do not include markdown.

The DSL must look like a specialized one-off rebuild script expressed as data.
Allowed object types:
canvas, style_tokens, panel, card, text, asset_slot, arrow, polyline, dashed_loop, legend, group, report_marker

Rules:
- Start with canvas and style_tokens objects.
- Convert all visible OCR/reference text into text objects with bbox_percent and font_size_pt.
- Use panel/card objects for containers that should be editable.
- Use asset_slot only for non-text visual icons, illustrations, screenshots, charts, tools, or characters.
- Every arrow/polyline/dashed_loop must include explicit path_percent or points_px with at least two points.
- Asset slots must include prompt_subject, asset_type, background_color_hex, generation_aspect_ratio when clear, and content_fill_target.
- Do not include a full reference image background object.
- Keep ids lowercase snake_case.

Experience from successful specialized scripts:
{PROFESSIONAL_REBUILD_EXPERIENCE}

Few-shot controlled DSL example:
{json.dumps(PROFESSIONAL_DSL_FEWSHOT, ensure_ascii=False)}

Return schema:
{{
  "summary": "...",
  "dsl_version": "1.0",
  "planner": {{"mode": "vlm_professional_script", "layout_pattern": "...", "vlm_status": "used"}},
  "canvas": {{"width_px": 1600, "height_px": 900, "width_in": 15.6, "height_in": 8.775, "background": "#FFFFFF"}},
  "objects": [
    {{"type":"canvas","id":"canvas","width_px":1600,"height_px":900,"width_in":15.6,"height_in":8.775,"background":"#FFFFFF"}},
    {{"type":"style_tokens","id":"style_tokens","font_family":"Arial","text_size_scale":1.0,"palette":["#FFFFFF"]}},
    {{"type":"panel","id":"stage_1","title":"...","bbox_percent":{{"x":0.1,"y":0.1,"w":0.3,"h":0.7}}}},
    {{"type":"text","id":"text_1","text":"...","bbox_percent":{{"x":0.1,"y":0.1,"w":0.2,"h":0.05}},"font_size_pt":10,"bold":true,"color_hex":"#333333","align":"center"}},
    {{"type":"asset_slot","id":"robot_icon","asset_id":"robot_icon","bbox_percent":{{"x":0.2,"y":0.3,"w":0.1,"h":0.2}},"asset_type":"character","prompt_subject":"robot assistant","background_color_hex":"#EAF3FF","content_fill_target":0.88}},
    {{"type":"polyline","id":"arrow_1","source_id":"a","target_id":"b","path_percent":[[0.1,0.2],[0.3,0.2]],"stroke_color":"#333333","stroke_width_pt":2.0,"dash_style":"solid"}}
  ]
}}

Baseline rebuild contracts:
{json.dumps(_brief_program(baseline_program), ensure_ascii=False)}

OCR/reference text geometry:
{json.dumps(text_geometry or {}, ensure_ascii=False)}
""".strip()
    try:
        result = call_vlm_json(prompt, [reference_path], model=model)
        result.setdefault("planner", {})
        result["planner"].update({"mode": "vlm_professional_script", "vlm_status": "used", "vlm_model": model})
        return result, {"status": "used", "mode": "vlm_professional_script", "model": model}
    except Exception as exc:
        fallback = fallback_professional_dsl(reference_path, baseline_program, baseline_program.get("text_program"))
        fallback["planner"] = {"mode": "fallback_after_vlm_error", "vlm_status": "fallback", "vlm_model": model, "error": str(exc)}
        return fallback, {"status": "fallback", "mode": "fallback_after_vlm_error", "model": model, "error": str(exc)}


def write_professional_notes(out: str | Path, planner_report: dict[str, Any], validation: dict[str, Any]) -> None:
    path = Path(out) / "professional_rebuild_notes.md"
    path.write_text(
        "# Professional Rebuild Notes\n\n"
        f"- Planner status: `{planner_report.get('status')}`\n"
        f"- Planner mode: `{planner_report.get('mode')}`\n"
        f"- Model: `{planner_report.get('model') or os.getenv('RFS_PROFESSIONAL_REBUILD_MODEL') or os.getenv('MODEL_VLM') or 'not configured'}`\n"
        f"- DSL validation: `{validation.get('status')}`\n"
        f"- Object count: `{validation.get('object_count')}`\n\n"
        "This workflow asks the VLM to generate a controlled DSL that mimics high-quality one-off rebuild scripts. "
        "The generated DSL is validated and interpreted by ResearchFigureStudio; arbitrary model-generated Python is never executed.\n",
        encoding="utf-8",
    )
