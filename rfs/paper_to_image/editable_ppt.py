from __future__ import annotations

from pathlib import Path
from typing import Any

from ..composition.pptx import compile_ppt
from ..utils import write_json
from .semantic_blueprint import compile_semantic_blueprint


_NODE_STYLES = {
    "inputs": {"fill_color": "#EDF5FC", "stroke_color": "#2A63A1", "text_color": "#244B72"},
    "modules": {"fill_color": "#EDF9F7", "stroke_color": "#1F756F", "text_color": "#195B57"},
    "outputs": {"fill_color": "#F2F8F3", "stroke_color": "#427E50", "text_color": "#315F3B"},
    "innovations": {"fill_color": "#FCF4EB", "stroke_color": "#B15C21", "text_color": "#8C481A"},
}

_RELATION_STYLES = {
    "feedback_loop": {"stroke_color": "#B15C21", "line_pattern": "dash", "stroke_width_pt": 2.0},
    "iteration": {"stroke_color": "#B15C21", "line_pattern": "dash", "stroke_width_pt": 2.0},
    "iterate": {"stroke_color": "#B15C21", "line_pattern": "dash", "stroke_width_pt": 2.0},
    "return_flow": {"stroke_color": "#B15C21", "line_pattern": "dash", "stroke_width_pt": 2.0},
    "branch": {"stroke_color": "#62529A", "stroke_width_pt": 1.8},
    "conditioning": {"stroke_color": "#1F756F", "line_pattern": "dash", "stroke_width_pt": 1.7},
    "feature_flow": {"stroke_color": "#2A63A1", "stroke_width_pt": 1.8},
    "data_flow": {"stroke_color": "#506F81", "stroke_width_pt": 1.7},
}


def _ratio_value(value: str | float | int | None) -> float:
    if isinstance(value, (float, int)):
        return max(0.5, min(3.0, float(value)))
    text = str(value or "16:9").strip().lower().replace("x", ":")
    try:
        if ":" in text:
            left, right = text.split(":", 1)
            return max(0.5, min(3.0, float(left) / max(float(right), 0.001)))
        return max(0.5, min(3.0, float(text)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 16 / 9


def _font_size(label: str, bbox: dict[str, Any]) -> float:
    width = float(bbox.get("w") or 0.12)
    if len(label) >= 30 or width < 0.12:
        return 12.0
    if len(label) >= 20:
        return 14.0
    return 16.0


def _relation_label_bbox(path: list[list[float]]) -> dict[str, float] | None:
    if len(path) < 2:
        return None
    point = path[len(path) // 2]
    x = max(0.02, min(0.84, float(point[0]) - 0.08))
    y = max(0.02, min(0.93, float(point[1]) - 0.022))
    return {"x": round(x, 6), "y": round(y, 6), "w": 0.16, "h": 0.044}


def build_semantic_figure_program(
    specification: dict[str, Any],
    *,
    aspect_ratio: str | float = "16:9",
    title: str | None = None,
    show_title: bool = False,
) -> dict[str, Any]:
    semantic_plan = compile_semantic_blueprint(specification)
    if not semantic_plan.get("applied"):
        raise ValueError(f"Cannot compile editable PPT semantic blueprint: {semantic_plan.get('reason') or 'not_applicable'}")

    ratio = _ratio_value(aspect_ratio)
    height_in = 7.5
    width_in = round(height_in * ratio, 3)
    semantic_nodes = []
    for node in semantic_plan["nodes"]:
        style = dict(_NODE_STYLES.get(str(node.get("field") or "modules"), _NODE_STYLES["modules"]))
        role = str(node.get("role") or "").casefold()
        if "data_source" in role or role in {"dataset", "source dataset"}:
            style = {"fill_color": "#F8F4EC", "stroke_color": "#896538", "text_color": "#684B28"}
        elif any(term in role for term in ("shared", "joint", "fusion")):
            style = {"fill_color": "#F4F1FA", "stroke_color": "#62529A", "text_color": "#4B3F78"}
        label = str(node.get("label") or node["id"])
        semantic_nodes.append({
            "id": node["id"],
            "label": label,
            "field": node.get("field"),
            "role": node.get("role"),
            "bbox_percent": node["bbox_percent"],
            "shape_kind": "rounded_rect",
            "stroke_width_pt": 1.6,
            "font_size_pt": _font_size(label, node["bbox_percent"]),
            "bold": True,
            "editable_in": "pptx",
            "z_index": 30,
            **style,
        })

    arrows = []
    labels = []
    for connector in semantic_plan["connectors"]:
        relation_type = str(connector.get("type") or "data_flow")
        style = dict(_RELATION_STYLES.get(relation_type, _RELATION_STYLES["data_flow"]))
        arrows.append({
            "id": connector["id"],
            "source": connector["source"],
            "target": connector["target"],
            "source_id": connector["source"],
            "target_id": connector["target"],
            "type": relation_type,
            "semantic_role": relation_type,
            "control_kind": "dashed_loop" if style.get("line_pattern") == "dash" else "elbow_connector",
            "route_style": connector.get("route_style"),
            "path_percent": connector.get("path_percent", []),
            "line_cap": "round",
            "arrowhead_size": "sm",
            "editable_in": "pptx",
            "render_policy": "ppt_shape_not_image_asset",
            **style,
        })
        relation_label = str(connector.get("label") or "").strip()
        label_bbox = _relation_label_bbox(connector.get("path_percent", [])) if relation_label else None
        if relation_label and label_bbox:
            labels.append({
                "id": f"label_{connector['id']}",
                "text": relation_label,
                "target_id": connector["id"],
                "role": "relation_label",
                "bbox_percent": label_bbox,
                "font_size_pt": 10,
                "bold": False,
                "color_hex": style["stroke_color"],
                "editable_in": "pptx",
            })

    program: dict[str, Any] = {
        "summary": "Editable PowerPoint figure compiled directly from the paper semantic contract.",
        "canvas": {"width_in": width_in, "height_in": height_in, "ratio": round(ratio, 6), "background": "#FFFFFF"},
        "style": {
            "palette": ["#2A63A1", "#1F756F", "#62529A", "#B15C21", "#427E50"],
            "arrow_weight_pt": 1.7,
            "font_family": "Arial",
        },
        "paper_brief": {"title_guess": title},
        "panels": [],
        "cards": [],
        "slots": [],
        "assets": [],
        "semantic_nodes": semantic_nodes,
        "arrows": arrows,
        "labels": labels,
        "groups": [],
        "export_targets": [{"type": "pptx", "path": "editable_composition.pptx", "role": "main_editable_source"}],
        "semantic_plan": semantic_plan,
    }
    if title and show_title:
        program["title_block"] = {
            "title": title,
            "subtitle": "Editable paper framework",
            "bbox_percent": {"x": 0.04, "y": 0.015, "w": 0.92, "h": 0.08},
            "title_font_size": 20,
            "subtitle_font_size": 9,
        }
    return program


def compile_semantic_ppt(
    specification: dict[str, Any],
    out: str | Path,
    *,
    aspect_ratio: str | float = "16:9",
    title: str | None = None,
    show_title: bool = False,
) -> dict[str, Any]:
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    program = build_semantic_figure_program(specification, aspect_ratio=aspect_ratio, title=title, show_title=show_title)
    write_json(root / "figure_program.json", program)
    pptx_path = compile_ppt(program, root)
    report = {
        "summary": "Paper semantic contract compiled to native editable PowerPoint shapes, text, and connectors.",
        "ok": pptx_path.exists(),
        "pptx": str(pptx_path),
        "figure_program": str(root / "figure_program.json"),
        "node_count": len(program["semantic_nodes"]),
        "connector_count": len(program["arrows"]),
        "relation_label_count": len(program["labels"]),
        "topology": program["semantic_plan"].get("topology"),
        "editable_layers": ["native_shapes", "native_text", "native_connectors"],
    }
    write_json(root / "semantic_ppt_report.json", report)
    return report
