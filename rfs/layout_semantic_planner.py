from __future__ import annotations

from pathlib import Path
from typing import Callable


ASSET_TYPES = {
    "character",
    "document_stack",
    "chart_card",
    "tool_icon",
    "tool_combo",
    "device",
    "screenshot_card",
    "legend_marker",
    "thin_tool",
    "generic",
}


def _center(box: dict) -> tuple[float, float]:
    return float(box["x"]) + float(box["w"]) / 2, float(box["y"]) + float(box["h"]) / 2


def _distance(a: dict, b: dict) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _text_regions(text_geometry: dict | None) -> list[dict]:
    if not isinstance(text_geometry, dict):
        return []
    items = text_geometry.get("text_regions") or text_geometry.get("regions") or []
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("bbox_percent"), dict)]


def _nearby_text(slot: dict, text_regions: list[dict]) -> list[str]:
    box = slot["bbox_percent"]
    ranked = sorted(text_regions, key=lambda region: _distance(box, region["bbox_percent"]))
    return [str(item.get("raw_text") or item.get("text") or "").strip() for item in ranked[:3] if str(item.get("raw_text") or item.get("text") or "").strip()]


def _panel_context(slot: dict, panels: list[dict]) -> str:
    panel_id = str(slot.get("panel_id") or "")
    for panel in panels:
        if str(panel.get("id")) == panel_id:
            return str(panel.get("title") or panel.get("id") or "")
    box = slot["bbox_percent"]
    containing = []
    sx, sy = _center(box)
    for panel in panels:
        pbox = panel.get("bbox_percent")
        if not isinstance(pbox, dict):
            continue
        if float(pbox["x"]) <= sx <= float(pbox["x"]) + float(pbox["w"]) and float(pbox["y"]) <= sy <= float(pbox["y"]) + float(pbox["h"]):
            containing.append(panel)
    if containing:
        panel = containing[0]
        return str(panel.get("title") or panel.get("id") or "")
    return ""


def _asset_type_from_text(slot: dict, text: str) -> str:
    raw = f"{slot.get('id', '')} {slot.get('paper_concept', '')} {slot.get('display_label', '')} {text}".lower()
    ratio = float(slot["bbox_percent"]["w"]) / max(float(slot["bbox_percent"]["h"]), 0.001)
    if "legend" in raw:
        return "legend_marker"
    if ratio >= 2.2:
        return "thin_tool"
    if any(term in raw for term in ["robot", "agent", "critic", "designer", "person", "avatar", "human", "interviewer"]):
        return "character"
    if any(term in raw for term in ["document", "paper", "text", "input", "file", "stack"]):
        return "document_stack"
    if any(term in raw for term in ["chart", "score", "graph", "plot", "card", "figure", "output", "final"]):
        return "chart_card"
    if any(term in raw for term in ["camera", "screen", "monitor", "phone", "device"]):
        return "device"
    if any(term in raw for term in ["ocr", "verify", "inspect", "search", "magnifier"]):
        return "tool_icon"
    if any(term in raw for term in ["tool", "erase", "magic", "wand", "palette", "synthesis"]):
        return "tool_combo"
    if ratio >= 1.35:
        return "chart_card"
    if ratio <= 0.78:
        return "character"
    return "generic"


def _relations(slot: dict, controls: list[dict]) -> tuple[list[str], list[str]]:
    slot_id = str(slot.get("id"))
    upstream = []
    downstream = []
    for control in controls:
        source = str(control.get("source_id") or control.get("source") or "")
        target = str(control.get("target_id") or control.get("target") or "")
        if target == slot_id and source:
            upstream.append(source)
        if source == slot_id and target:
            downstream.append(target)
    return sorted(set(upstream)), sorted(set(downstream))


def _apply_adapter(slots: list[dict], adapter_result: dict | list[dict]) -> dict[str, dict]:
    records = adapter_result.get("slots", []) if isinstance(adapter_result, dict) else adapter_result
    by_id = {}
    for item in records or []:
        if not isinstance(item, dict):
            continue
        slot_id = str(item.get("id") or item.get("slot_id") or "")
        if not slot_id:
            continue
        by_id[slot_id] = item
    return by_id


def plan_slot_semantics(
    reference_path: str | Path,
    slots: list[dict],
    panels: list[dict],
    controls: list[dict],
    text_geometry: dict | None,
    semantic_adapter: Callable[[str | Path, list[dict], list[dict], list[dict], dict | None], dict | list[dict]] | None = None,
) -> tuple[list[dict], dict]:
    regions = _text_regions(text_geometry)
    warnings = []
    adapter_by_id = {}
    if semantic_adapter:
        try:
            adapter_by_id = _apply_adapter(slots, semantic_adapter(reference_path, slots, panels, controls, text_geometry))
        except Exception as exc:
            warnings.append(f"semantic_adapter_failed:{exc}")
    planned = []
    for slot in slots:
        slot_id = str(slot.get("id"))
        texts = _nearby_text(slot, regions)
        nearby = " | ".join(texts)
        upstream, downstream = _relations(slot, controls)
        panel_context = _panel_context(slot, panels)
        asset_type = _asset_type_from_text(slot, nearby)
        prompt_subject = nearby or str(slot.get("paper_concept") or slot_id)
        semantic_role = asset_type
        override = adapter_by_id.get(slot_id, {})
        if override:
            asset_type = str(override.get("asset_type") or asset_type)
            if asset_type not in ASSET_TYPES:
                warnings.append(f"unknown_asset_type:{slot_id}:{asset_type}")
                asset_type = "generic"
            semantic_role = str(override.get("semantic_role") or semantic_role)
            prompt_subject = str(override.get("prompt_subject") or prompt_subject)
            if override.get("nearby_text"):
                nearby = " | ".join(override["nearby_text"]) if isinstance(override["nearby_text"], list) else str(override["nearby_text"])
        enriched = dict(slot)
        enriched.update({
            "semantic_role": semantic_role,
            "asset_type": asset_type,
            "nearby_text": texts if not override.get("nearby_text") else override.get("nearby_text"),
            "panel_context": panel_context,
            "upstream_ids": upstream,
            "downstream_ids": downstream,
            "prompt_subject": prompt_subject,
        })
        planned.append(enriched)
    return planned, {
        "summary": "Slot semantic planning report.",
        "status": "ok",
        "slot_count": len(planned),
        "text_region_count": len(regions),
        "warnings": warnings,
        "slots": [{
            "slot_id": item["id"],
            "semantic_role": item.get("semantic_role"),
            "asset_type": item.get("asset_type"),
            "nearby_text": item.get("nearby_text"),
            "panel_context": item.get("panel_context"),
            "upstream_ids": item.get("upstream_ids"),
            "downstream_ids": item.get("downstream_ids"),
            "prompt_subject": item.get("prompt_subject"),
        } for item in planned],
    }
