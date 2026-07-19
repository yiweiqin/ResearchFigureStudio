from __future__ import annotations

from pathlib import Path
from typing import Any

from .editable_rebuild import _supported_aspect_ratio
from .utils import write_json


def _style_from_dsl(dsl: dict[str, Any]) -> dict[str, Any]:
    style_objects = [obj for obj in dsl.get("objects", []) if obj.get("type") == "style_tokens"]
    style = style_objects[0] if style_objects else {}
    palette = style.get("palette") if isinstance(style.get("palette"), list) else ["#FFFFFF", "#4A90C2", "#E17721", "#4B9B52"]
    panel_styles = {}
    canvas_background = dsl.get("canvas", {}).get("background") or "#FFFFFF"
    for obj in dsl.get("objects", []):
        if obj.get("type") != "panel":
            continue
        fill_color = obj.get("fill_color") or canvas_background
        if str(fill_color).lower() in {"none", "transparent", "no_fill"}:
            fill_color = canvas_background
        panel_styles[obj["id"]] = {
            "fill_color": fill_color,
            "stroke_color": obj.get("stroke_color") or palette[min(1, len(palette) - 1)],
            "header_color": obj.get("header_color") or obj.get("stroke_color") or palette[min(1, len(palette) - 1)],
        }
    return {
        "palette": palette,
        "reference_palette": palette,
        "font_family": style.get("font_family") or "Arial",
        "text_size_scale": style.get("text_size_scale") or 1.0,
        "panel_styles": panel_styles,
        "arrow_weight_pt": 1.7,
    }


def dsl_to_program(dsl: dict[str, Any], out: str | Path | None = None) -> dict[str, Any]:
    canvas = dsl["canvas"]
    panels = []
    cards = []
    slots = []
    arrows = []
    text_items = []
    labels = []
    for obj in dsl.get("objects", []):
        obj_type = obj.get("type")
        if obj_type == "panel":
            panels.append({
                "id": obj["id"],
                "title": obj.get("title") or "",
                "bbox_percent": obj["bbox_percent"],
                "editable_in": "pptx",
            })
        elif obj_type == "card":
            fill_color = obj.get("fill_color")
            if str(fill_color).lower() in {"none", "transparent", "no_fill"}:
                fill_color = canvas.get("background") or "#FFFFFF"
            cards.append({
                "id": obj["id"],
                "title": obj.get("title") or "",
                "panel_id": obj.get("panel_id"),
                "bbox_percent": obj["bbox_percent"],
                "editable_in": "pptx",
                "fill_color": fill_color,
                "stroke_color": obj.get("stroke_color"),
            })
        elif obj_type == "asset_slot":
            bbox = obj["bbox_percent"]
            ratio = float(bbox["w"]) / max(float(bbox["h"]), 0.001)
            slots.append({
                "id": obj["id"],
                "asset_id": obj.get("asset_id") or obj["id"],
                "panel_id": obj.get("panel_id"),
                "bbox_percent": bbox,
                "paper_concept": obj.get("prompt_subject") or obj["id"],
                "display_label": "",
                "composition_type": "full_frame_icon",
                "show_slot_caption": False,
                "z_index": int(obj.get("z_index") or 20),
                "asset_type": obj.get("asset_type") or "generic",
                "slot_type": obj.get("asset_type") or "generic",
                "semantic_role": obj.get("semantic_role"),
                "prompt_subject": obj.get("prompt_subject") or obj["id"],
                "nearby_text": obj.get("nearby_text") or [],
                "panel_context": obj.get("panel_context"),
                "generation_aspect_ratio": obj.get("generation_aspect_ratio") or _supported_aspect_ratio(float(bbox["w"]), float(bbox["h"])),
                "content_fill_target": obj.get("content_fill_target"),
                "slot_aspect_ratio": round(ratio, 4),
            })
        elif obj_type == "text":
            text_items.append({
                "id": obj["id"],
                "text": obj.get("text") or "",
                "role": obj.get("role") or "label",
                "target_id": obj.get("target_id"),
                "bbox_percent": obj["bbox_percent"],
                "font_size_pt": float(obj.get("font_size_pt") or 9),
                "font_family_guess": obj.get("font_family") or "Arial",
                "color_hex": obj.get("color_hex") or "#263747",
                "bold": bool(obj.get("bold")),
                "align": obj.get("align") or "center",
                "fit_strategy": "professional_dsl_bbox",
                "reference_binding": "professional_dsl",
                "visible": obj.get("visible", True),
            })
        elif obj_type == "legend":
            labels.append({
                "id": obj["id"],
                "text": obj.get("text") or obj.get("title") or "",
                "bbox_percent": obj["bbox_percent"],
                "font_size_pt": float(obj.get("font_size_pt") or 9),
                "bold": bool(obj.get("bold", True)),
                "color_hex": obj.get("color_hex") or "#263747",
                "align": obj.get("align") or "center",
            })
        elif obj_type in {"arrow", "polyline", "dashed_loop"}:
            arrows.append({
                "id": obj["id"],
                "source_id": obj.get("source_id"),
                "target_id": obj.get("target_id"),
                "control_kind": "dashed_loop" if obj_type == "dashed_loop" else "elbow_connector" if obj_type == "polyline" else "straight_arrow",
                "path_percent": obj.get("path_percent") or [],
                "stroke_color": obj.get("stroke_color") or "#333333",
                "stroke_width_pt": float(obj.get("stroke_width_pt") or 1.7),
                "line_pattern": "dash" if obj_type == "dashed_loop" or str(obj.get("dash_style")).lower() in {"dash", "dashed"} else "solid",
                "dash_style": "dashed" if obj_type == "dashed_loop" or str(obj.get("dash_style")).lower() in {"dash", "dashed"} else "solid",
                "arrowhead_size": obj.get("arrowhead_size") or "sm",
                "editable_in": "pptx",
                "render_policy": "ppt_shape_not_image_asset",
            })
    program = {
        "canvas": canvas,
        "style": _style_from_dsl(dsl),
        "title_block": {"title": "", "subtitle": "", "bbox_percent": {"x": 0.04, "y": 0.02, "w": 0.92, "h": 0.04}},
        "panels": panels,
        "cards": cards,
        "slots": slots,
        "assets": [{"id": slot["asset_id"], "path": f"assets/{slot['asset_id']}.png", "source": "slot_asset"} for slot in slots],
        "arrows": arrows,
        "labels": labels,
        "groups": [],
        "text_program": {
            "summary": "Editable text program generated from professional rebuild DSL.",
            "items": text_items,
        },
        "export_targets": [{"type": "pptx", "path": "editable_composition.pptx"}],
    }
    if out is not None:
        write_json(Path(out) / "figure_program.json", program)
        write_json(Path(out) / "text_program.json", program["text_program"])
        write_json(Path(out) / "reference_controls.json", {
            "summary": "Professional DSL control layer.",
            "mode": "professional_dsl",
            "vlm_status": dsl.get("planner", {}).get("vlm_status", "fallback"),
            "arrows": arrows,
        })
        write_json(Path(out) / "slot_inventory.json", {"summary": "Professional DSL asset slot inventory.", "slots": slots})
    return program
