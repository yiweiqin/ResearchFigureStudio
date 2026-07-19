from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from .utils import write_json


ALLOWED_OBJECT_TYPES = {
    "canvas",
    "style_tokens",
    "panel",
    "card",
    "text",
    "asset_slot",
    "arrow",
    "polyline",
    "dashed_loop",
    "legend",
    "group",
    "report_marker",
}


def bbox(x: float, y: float, w: float, h: float) -> dict[str, float]:
    x = max(0.0, min(0.995, float(x)))
    y = max(0.0, min(0.995, float(y)))
    w = max(0.001, min(float(w), 1.0 - x))
    h = max(0.001, min(float(h), 1.0 - y))
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def canvas_from_reference(reference: str | Path) -> dict[str, Any]:
    with Image.open(reference) as image:
        width_px, height_px = image.size
    ratio = width_px / max(height_px, 1)
    width_in = max(10.0, min(15.6, 7.5 * ratio))
    return {
        "width_px": width_px,
        "height_px": height_px,
        "width_in": round(width_in, 3),
        "height_in": round(width_in / ratio, 3),
        "background": "#FFFFFF",
    }


def _as_bbox(value: Any, errors: list[str], object_id: str) -> dict[str, float] | None:
    if not isinstance(value, dict):
        errors.append(f"{object_id} missing bbox_percent")
        return None
    required = ["x", "y", "w", "h"]
    if any(key not in value for key in required):
        errors.append(f"{object_id} bbox_percent missing x/y/w/h")
        return None
    original = {key: float(value[key]) for key in required}
    clamped = bbox(original["x"], original["y"], original["w"], original["h"])
    if any(abs(float(original[key]) - float(clamped[key])) > 0.0001 for key in required):
        errors.append(f"{object_id} bbox_percent was clamped")
    return clamped


def _normalize_points(points: Any, canvas: dict[str, Any], errors: list[str], object_id: str) -> list[list[float]]:
    if not isinstance(points, list) or len(points) < 2:
        errors.append(f"{object_id} missing at least two explicit path points")
        return []
    width_px = float(canvas.get("width_px") or 1)
    height_px = float(canvas.get("height_px") or 1)
    normalized: list[list[float]] = []
    for point in points:
        if not isinstance(point, list) or len(point) < 2:
            errors.append(f"{object_id} has invalid path point")
            continue
        px = float(point[0])
        py = float(point[1])
        if px > 1.0 or py > 1.0:
            px = px / max(width_px, 1)
            py = py / max(height_px, 1)
        normalized.append([round(max(0.0, min(1.0, px)), 4), round(max(0.0, min(1.0, py)), 4)])
    if len(normalized) < 2:
        errors.append(f"{object_id} has fewer than two valid path points")
    return normalized


def fallback_professional_dsl(reference: str | Path, baseline_program: dict | None = None, text_program: dict | None = None) -> dict[str, Any]:
    canvas = canvas_from_reference(reference)
    if baseline_program and isinstance(baseline_program.get("canvas"), dict):
        canvas = {**canvas, **baseline_program["canvas"]}
    panels = list((baseline_program or {}).get("panels") or [])
    cards = list((baseline_program or {}).get("cards") or [])
    slots = list((baseline_program or {}).get("slots") or [])
    arrows = list((baseline_program or {}).get("arrows") or [])
    text_items = list((text_program or {}).get("items") or [])
    objects: list[dict[str, Any]] = [
        {"type": "canvas", "id": "canvas", **canvas},
        {
            "type": "style_tokens",
            "id": "style_tokens",
            "font_family": "Arial",
            "text_size_scale": 1.0,
            "palette": (baseline_program or {}).get("style", {}).get("palette", ["#FFFFFF", "#4A90C2", "#E17721", "#4B9B52"]),
        },
    ]
    for panel in panels:
        objects.append({
            "type": "panel",
            "id": panel.get("id"),
            "title": panel.get("title") or "",
            "bbox_percent": panel.get("bbox_percent"),
            "fill_color": panel.get("fill_color"),
            "stroke_color": panel.get("stroke_color"),
        })
    for card in cards:
        objects.append({
            "type": "card",
            "id": card.get("id"),
            "title": card.get("title") or "",
            "panel_id": card.get("panel_id"),
            "bbox_percent": card.get("bbox_percent"),
            "fill_color": card.get("fill_color"),
            "stroke_color": card.get("stroke_color"),
        })
    for slot in slots:
        objects.append({
            "type": "asset_slot",
            "id": slot.get("id"),
            "asset_id": slot.get("asset_id") or slot.get("id"),
            "panel_id": slot.get("panel_id"),
            "bbox_percent": slot.get("bbox_percent"),
            "asset_type": slot.get("asset_type") or "generic",
            "semantic_role": slot.get("semantic_role"),
            "prompt_subject": slot.get("prompt_subject") or slot.get("paper_concept") or slot.get("id"),
            "background_color_hex": canvas.get("background") or "#FFFFFF",
            "generation_aspect_ratio": slot.get("generation_aspect_ratio"),
            "content_fill_target": slot.get("content_fill_target"),
        })
    for item in text_items:
        objects.append({
            "type": "text",
            "id": item.get("id"),
            "text": item.get("text") or "",
            "role": item.get("role") or "label",
            "target_id": item.get("target_id"),
            "bbox_percent": item.get("bbox_percent"),
            "font_size_pt": item.get("font_size_pt") or 9,
            "font_family": item.get("font_family_guess") or "Arial",
            "color_hex": item.get("color_hex") or "#263747",
            "bold": bool(item.get("bold")),
            "align": item.get("align") or "center",
        })
    for arrow in arrows:
        kind = str(arrow.get("control_kind") or "arrow")
        objects.append({
            "type": "dashed_loop" if "loop" in kind else "polyline" if len(arrow.get("path_percent") or []) > 2 else "arrow",
            "id": arrow.get("id"),
            "source_id": arrow.get("source_id") or arrow.get("source"),
            "target_id": arrow.get("target_id") or arrow.get("target"),
            "path_percent": arrow.get("path_percent"),
            "stroke_color": arrow.get("stroke_color") or "#333333",
            "stroke_width_pt": arrow.get("stroke_width_pt") or 1.7,
            "dash_style": arrow.get("dash_style") or arrow.get("line_pattern") or "solid",
            "arrowhead": True,
        })
    return {
        "summary": "Fallback professional DSL generated from baseline rebuild contracts.",
        "dsl_version": "1.0",
        "planner": {"mode": "fallback_baseline"},
        "canvas": canvas,
        "objects": objects,
    }


def validate_and_normalize_dsl(dsl: dict[str, Any], reference: str | Path, out: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = deepcopy(dsl if isinstance(dsl, dict) else {})
    errors: list[str] = []
    warnings: list[str] = []
    canvas = normalized.get("canvas") if isinstance(normalized.get("canvas"), dict) else canvas_from_reference(reference)
    if not canvas.get("width_px") or not canvas.get("height_px"):
        canvas = {**canvas_from_reference(reference), **canvas}
    normalized["canvas"] = canvas
    objects = normalized.get("objects")
    if not isinstance(objects, list):
        objects = []
        errors.append("objects must be a list")
    seen: set[str] = set()
    valid_objects: list[dict[str, Any]] = []
    for idx, obj in enumerate(objects):
        if not isinstance(obj, dict):
            errors.append(f"object_{idx} must be an object")
            continue
        object_type = str(obj.get("type") or "")
        object_id = str(obj.get("id") or f"{object_type}_{idx}")
        if object_type not in ALLOWED_OBJECT_TYPES:
            errors.append(f"{object_id} unknown object type {object_type}")
            continue
        if object_id in seen:
            errors.append(f"duplicate id {object_id}")
            continue
        seen.add(object_id)
        obj["id"] = object_id
        if object_type in {"panel", "card", "text", "asset_slot", "legend"}:
            bb = _as_bbox(obj.get("bbox_percent"), errors, object_id)
            if bb is None:
                continue
            obj["bbox_percent"] = bb
        if object_type in {"arrow", "polyline", "dashed_loop"}:
            if isinstance(obj.get("path_percent"), list):
                obj["path_percent"] = _normalize_points(obj["path_percent"], {"width_px": 1, "height_px": 1}, errors, object_id)
            else:
                obj["path_percent"] = _normalize_points(obj.get("points_px"), canvas, errors, object_id)
            if len(obj["path_percent"]) < 2:
                continue
        if object_type == "asset_slot":
            text = " ".join(str(obj.get(key) or "") for key in ["prompt", "prompt_subject"])
            forbidden_hits = [term for term in ["full diagram", "whole diagram", "panel border", "readable text"] if term in text.lower()]
            if forbidden_hits:
                warnings.append(f"{object_id} asset prompt mentions forbidden concepts: {', '.join(forbidden_hits)}")
        valid_objects.append(obj)
    normalized["objects"] = valid_objects
    status = "pass" if not errors else "error"
    report = {
        "summary": "Professional rebuild DSL validation report.",
        "status": status,
        "allowed_object_types": sorted(ALLOWED_OBJECT_TYPES),
        "object_count": len(valid_objects),
        "errors": errors,
        "warnings": warnings,
        "counts": {
            name: sum(1 for obj in valid_objects if obj.get("type") == name)
            for name in sorted(ALLOWED_OBJECT_TYPES)
        },
    }
    if out is not None:
        write_json(Path(out) / "professional_rebuild_validation.json", report)
    return normalized, report
