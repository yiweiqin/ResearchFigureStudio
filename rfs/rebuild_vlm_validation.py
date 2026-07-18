from __future__ import annotations

from pathlib import Path

from .layout_semantic_planner import ASSET_TYPES
from .utils import write_json


def _valid_bbox(bbox: dict | None) -> bool:
    if not isinstance(bbox, dict):
        return False
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        w = float(bbox["w"])
        h = float(bbox["h"])
    except Exception:
        return False
    return 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001


def _duplicate_ids(items: list[dict]) -> list[str]:
    seen = set()
    duplicates = []
    for item in items:
        item_id = str(item.get("id") or item.get("slot_id") or "")
        if not item_id:
            continue
        if item_id in seen and item_id not in duplicates:
            duplicates.append(item_id)
        seen.add(item_id)
    return duplicates


def build_rebuild_vlm_validation_report(
    out_dir: str | Path,
    reference_geometry: dict,
    reference_controls: dict,
    semantic_report: dict,
    asset_summary: dict | None = None,
) -> dict:
    panels = [item for item in reference_geometry.get("panels", []) if isinstance(item, dict)]
    slots = [item for item in reference_geometry.get("slots", []) if isinstance(item, dict)]
    cards = [item for item in reference_geometry.get("cards", []) if isinstance(item, dict)]
    legends = [item for item in reference_geometry.get("legend_regions", []) if isinstance(item, dict)]
    arrows = [item for item in reference_controls.get("arrows", []) if isinstance(item, dict)]
    semantic_slots = [item for item in semantic_report.get("slots", []) if isinstance(item, dict)]
    slot_ids = {str(item.get("id")) for item in slots}

    invalid_layout_bboxes = [
        str(item.get("id") or "")
        for item in panels + slots + cards + legends
        if not _valid_bbox(item.get("bbox_percent"))
    ]
    clamped_bboxes = [
        str(item.get("id") or "")
        for item in panels + slots + cards + legends
        if bool(item.get("bbox_was_clamped"))
    ]
    invalid_arrows = []
    for arrow in arrows:
        source = str(arrow.get("source_id") or arrow.get("source") or "")
        target = str(arrow.get("target_id") or arrow.get("target") or "")
        path = arrow.get("path_percent")
        if source not in slot_ids or target not in slot_ids or not isinstance(path, list) or len(path) < 2:
            invalid_arrows.append(str(arrow.get("id") or ""))
    invalid_semantic_types = [
        str(item.get("slot_id") or "")
        for item in semantic_slots
        if str(item.get("asset_type") or "") not in ASSET_TYPES
    ]
    prompt_subject_missing = [
        str(item.get("slot_id") or "")
        for item in semantic_slots
        if not str(item.get("prompt_subject") or "").strip()
    ]
    warnings = []
    if invalid_layout_bboxes:
        warnings.append(f"{len(invalid_layout_bboxes)} invalid layout bbox(es)")
    if clamped_bboxes:
        warnings.append(f"{len(clamped_bboxes)} VLM bbox(es) were clamped")
    if invalid_arrows:
        warnings.append(f"{len(invalid_arrows)} invalid arrow(s)")
    if invalid_semantic_types:
        warnings.append(f"{len(invalid_semantic_types)} invalid semantic asset type(s)")
    if prompt_subject_missing:
        warnings.append(f"{len(prompt_subject_missing)} slot prompt_subject value(s) missing")

    report = {
        "summary": "VLM adapter validation report for rebuild-editable.",
        "status": "pass" if not warnings else "warning",
        "warnings": warnings,
        "layout": {
            "layout_mode": reference_geometry.get("layout_mode"),
            "vlm_status": reference_geometry.get("vlm_status"),
            "vlm_model": reference_geometry.get("vlm_model"),
            "panel_count": len(panels),
            "card_count": len(cards),
            "slot_count": len(slots),
            "legend_region_count": len(legends),
            "invalid_bbox_ids": invalid_layout_bboxes,
            "clamped_bbox_ids": clamped_bboxes,
            "duplicate_panel_ids": _duplicate_ids(panels),
            "duplicate_slot_ids": _duplicate_ids(slots),
            "warnings": reference_geometry.get("warnings", []),
        },
        "control": {
            "control_mode": reference_controls.get("mode"),
            "vlm_status": reference_controls.get("vlm_status"),
            "vlm_model": reference_controls.get("vlm_model"),
            "arrow_count": len(arrows),
            "invalid_arrow_ids": invalid_arrows,
            "arrows_with_path_count": sum(1 for arrow in arrows if isinstance(arrow.get("path_percent"), list) and len(arrow.get("path_percent")) >= 2),
            "dashed_arrow_count": sum(1 for arrow in arrows if str(arrow.get("dash_style") or arrow.get("line_pattern") or "").lower() in {"dash", "dashed"}),
            "warnings": reference_controls.get("warnings", []),
        },
        "semantic": {
            "semantic_vlm_status": semantic_report.get("semantic_vlm_status"),
            "vlm_model": semantic_report.get("vlm_model"),
            "slot_count": len(semantic_slots),
            "invalid_asset_type_ids": invalid_semantic_types,
            "prompt_subject_missing_ids": prompt_subject_missing,
            "prompt_subject_coverage_percent": round((len(semantic_slots) - len(prompt_subject_missing)) / max(len(semantic_slots), 1) * 100, 2),
            "nearby_text_usage_percent": round(sum(1 for item in semantic_slots if item.get("nearby_text")) / max(len(semantic_slots), 1) * 100, 2),
            "warnings": semantic_report.get("warnings", []),
        },
        "asset_generation": {
            "asset_mode": (asset_summary or {}).get("asset_mode"),
            "api_requests_attempted": (asset_summary or {}).get("api_requests_attempted", 0),
        },
    }
    write_json(Path(out_dir) / "rebuild_vlm_validation_report.json", report)
    return report
