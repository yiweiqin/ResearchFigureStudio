from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..utils import read_json, write_json


def load_paper_semantic_contract(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    return {
        "summary": "Paper-grounded semantic contract for editable figure reconstruction.",
        "source_run_dir": str(root.resolve()),
        "paper_review": read_json(root / "paper_review.json"),
        "figure_specification": read_json(root / "figure_specification.json"),
        "paper_summary": read_json(root / "paper_summary.json"),
        "design_plan": read_json(root / "design_plan.json"),
        "layout_intent": read_json(root / "layout_intent.json"),
        "style_plan": read_json(root / "style_plan.json"),
    }


def _text(item: dict, fallback: str = "") -> str:
    for key in ("visible_label", "name", "text", "statement", "label", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return fallback


def _entities(contract: dict) -> list[dict]:
    spec = contract.get("figure_specification") if isinstance(contract.get("figure_specification"), dict) else contract
    entities: list[dict] = []
    for field, role in (("inputs", "input"), ("modules", "module"), ("outputs", "output"), ("innovations", "innovation")):
        values = spec.get(field) if isinstance(spec.get(field), list) else []
        for index, raw in enumerate(values, start=1):
            if not isinstance(raw, dict):
                continue
            label = _text(raw)
            if not label:
                continue
            entity_id = str(raw.get("id") or raw.get("name") or f"{role}_{index:02d}").strip()
            entities.append({
                "id": entity_id,
                "label": label,
                "role": role,
                "evidence_ids": list(raw.get("evidence_ids") or []),
                "source": raw,
            })
    return entities


def _tokens(value: object) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(token) > 1}


def _object_text(obj: dict) -> str:
    return " ".join(str(obj.get(key) or "") for key in ("id", "title", "label", "name", "semantic_type", "description", "prompt"))


def _center(obj: dict) -> tuple[float, float]:
    box = obj.get("bbox_percent") if isinstance(obj.get("bbox_percent"), dict) else {}
    return float(box.get("x") or 0) + float(box.get("w") or 0) / 2, float(box.get("y") or 0) + float(box.get("h") or 0) / 2


def _assign_entities(entities: list[dict], program: dict) -> tuple[dict[str, dict], list[dict]]:
    objects = [item for item in program.get("slots", []) if isinstance(item, dict) and isinstance(item.get("bbox_percent"), dict)]
    if len(objects) < len(entities):
        seen = {str(item.get("id")) for item in objects}
        objects.extend(
            item for item in program.get("cards", []) + program.get("panels", [])
            if isinstance(item, dict) and isinstance(item.get("bbox_percent"), dict) and str(item.get("id")) not in seen
        )
    objects.sort(key=lambda item: (_center(item)[0], _center(item)[1], str(item.get("id") or "")))
    available = list(objects)
    mapping: dict[str, dict] = {}
    records: list[dict] = []
    for entity in entities:
        entity_tokens = _tokens(entity["label"]) | _tokens(entity["id"])
        scored = []
        for obj in available:
            obj_tokens = _tokens(_object_text(obj))
            score = len(entity_tokens & obj_tokens) / max(1, len(entity_tokens | obj_tokens))
            scored.append((score, -_center(obj)[0], obj))
        if not scored:
            records.append({"entity_id": entity["id"], "label": entity["label"], "status": "unmapped"})
            continue
        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        chosen = scored[0][2] if scored[0][0] > 0 else available[0]
        available.remove(chosen)
        mapping[entity["id"]] = chosen
        records.append({
            "entity_id": entity["id"],
            "label": entity["label"],
            "role": entity["role"],
            "object_id": chosen.get("id"),
            "match_score": round(max(0.0, scored[0][0]), 4),
            "status": "mapped",
        })
    return mapping, records


def _inside(inner: dict, outer: dict) -> bool:
    cx = float(inner.get("x") or 0) + float(inner.get("w") or 0) / 2
    cy = float(inner.get("y") or 0) + float(inner.get("h") or 0) / 2
    return float(outer.get("x") or 0) <= cx <= float(outer.get("x") or 0) + float(outer.get("w") or 0) and float(outer.get("y") or 0) <= cy <= float(outer.get("y") or 0) + float(outer.get("h") or 0)


def _label_bbox(obj: dict) -> dict[str, float]:
    box = obj["bbox_percent"]
    x, y, w, h = (float(box[key]) for key in ("x", "y", "w", "h"))
    label_h = min(0.055, max(0.026, h * 0.18))
    return {"x": round(x, 4), "y": round(max(0.0, y), 4), "w": round(w, 4), "h": round(label_h, 4)}


def _anchor(source: dict, target: dict) -> list[list[float]]:
    sx, sy = _center(source)
    tx, ty = _center(target)
    sb, tb = source["bbox_percent"], target["bbox_percent"]
    if abs(tx - sx) >= abs(ty - sy):
        start = [float(sb["x"]) + (float(sb["w"]) if tx >= sx else 0.0), sy]
        end = [float(tb["x"]) + (0.0 if tx >= sx else float(tb["w"])), ty]
        mid = (start[0] + end[0]) / 2
        points = [start, [mid, start[1]], [mid, end[1]], end]
    else:
        start = [sx, float(sb["y"]) + (float(sb["h"]) if ty >= sy else 0.0)]
        end = [tx, float(tb["y"]) + (0.0 if ty >= sy else float(tb["h"]))]
        mid = (start[1] + end[1]) / 2
        points = [start, [start[0], mid], [end[0], mid], end]
    clean: list[list[float]] = []
    for point in points:
        rounded = [round(max(0.0, min(1.0, point[0])), 4), round(max(0.0, min(1.0, point[1])), 4)]
        if not clean or clean[-1] != rounded:
            clean.append(rounded)
    return clean


def apply_paper_semantic_contract(program: dict, contract: dict, out_dir: str | Path) -> tuple[dict, dict]:
    entities = _entities(contract)
    mapping, mapping_records = _assign_entities(entities, program)
    mapped_boxes = [obj["bbox_percent"] for obj in mapping.values()]
    text_program = program.get("text_program") if isinstance(program.get("text_program"), dict) else {"items": []}
    existing = [item for item in text_program.get("items", []) if isinstance(item, dict)]
    preserved = [item for item in existing if not any(_inside(item.get("bbox_percent") or {}, box) for box in mapped_boxes)]
    semantic_text = []
    for entity in entities:
        obj = mapping.get(entity["id"])
        if not obj:
            continue
        box = _label_bbox(obj)
        semantic_text.append({
            "id": f"semantic_text_{entity['id']}",
            "text": entity["label"],
            "role": f"paper_{entity['role']}_label",
            "target_id": obj.get("id"),
            "semantic_entity_id": entity["id"],
            "semantic_evidence_ids": entity["evidence_ids"],
            "bbox_percent": box,
            "center_percent": {"x": round(box["x"] + box["w"] / 2, 4), "y": round(box["y"] + box["h"] / 2, 4)},
            "width_percent": box["w"],
            "height_percent": box["h"],
            "font_size_pt": 10.0,
            "color_hex": "#263747",
            "bold": entity["role"] in {"module", "innovation"},
            "align": "center",
            "font_family_guess": "Arial",
            "fit_strategy": "paper_semantic_contract_exact_label",
            "editable_in": "pptx",
            "visible": True,
            "layer_ownership": "editable_text_layer",
        })
    text_program = {
        **text_program,
        "summary": "Editable text with paper-grounded exact labels overriding image-derived labels in mapped semantic objects.",
        "semantic_authority": "paper_ground_truth",
        "items": preserved + semantic_text,
    }
    program["text_program"] = text_program
    program["text_program_path"] = "text_program.json"

    spec = contract.get("figure_specification") if isinstance(contract.get("figure_specification"), dict) else contract
    semantic_arrows = []
    skipped_relations = []
    for index, relation in enumerate(spec.get("relations") if isinstance(spec.get("relations"), list) else [], start=1):
        if not isinstance(relation, dict):
            continue
        source_id = str(relation.get("source") or relation.get("source_id") or "")
        target_id = str(relation.get("target") or relation.get("target_id") or "")
        source, target = mapping.get(source_id), mapping.get(target_id)
        if not source or not target:
            skipped_relations.append({"source": source_id, "target": target_id, "reason": "unmapped_endpoint"})
            continue
        semantic_arrows.append({
            "id": str(relation.get("id") or f"semantic_relation_{index:02d}"),
            "source_id": str(source.get("id")),
            "target_id": str(target.get("id")),
            "semantic_source_id": source_id,
            "semantic_target_id": target_id,
            "relation_type": str(relation.get("type") or relation.get("relation_type") or "data_flow"),
            "label": str(relation.get("label") or relation.get("statement") or ""),
            "evidence_ids": list(relation.get("evidence_ids") or []),
            "path_percent": _anchor(source, target),
            "render_style": "elbow_connector",
            "route_intent": "paper_semantic_relation",
            "stroke_color": "#3F5063",
            "stroke_width_pt": 1.8,
            "arrowhead": "triangle",
            "editable_in": "pptx",
        })
    if semantic_arrows:
        program["arrows"] = semantic_arrows

    report = {
        "summary": "Paper semantic contract application report.",
        "status": "pass" if len(mapping) == len(entities) and not skipped_relations else "warning",
        "semantic_authority": "paper_ground_truth",
        "visual_authority": "generated_reference_image",
        "entity_count": len(entities),
        "mapped_entity_count": len(mapping),
        "relation_count": len(spec.get("relations") or []),
        "mapped_relation_count": len(semantic_arrows),
        "mappings": mapping_records,
        "skipped_relations": skipped_relations,
        "policy": "exact labels and scientific relations come from the paper contract; the image supplies layout and style only",
    }
    out = Path(out_dir)
    write_json(out / "paper_semantic_contract.json", contract)
    write_json(out / "semantic_binding_report.json", report)
    write_json(out / "text_program.json", text_program)
    return program, report
