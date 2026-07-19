from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .utils import write_json


ALLOWED_PATCH_FIELDS = {"bbox_percent", "font_size_pt", "path_percent", "points_px", "stroke_color", "stroke_width_pt", "prompt_subject", "background_color_hex", "generation_aspect_ratio", "content_fill_target"}


def apply_professional_dsl_patch(dsl: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    objects = dsl.get("objects", [])
    if not isinstance(objects, list):
        return dsl, {"status": "rejected", "reason": "dsl objects must be a list", "applied_count": 0, "rejected": []}
    by_id = {str(obj.get("id")): obj for obj in objects if isinstance(obj, dict)}
    rejected: list[dict[str, Any]] = []
    applied = 0
    for op in patch.get("operations", []) if isinstance(patch.get("operations"), list) else []:
        if not isinstance(op, dict) or op.get("op") != "replace":
            rejected.append({"operation": op, "reason": "only replace operations are allowed"})
            continue
        object_id = str(op.get("object_id") or "")
        field = str(op.get("field") or "")
        if object_id not in by_id:
            rejected.append({"operation": op, "reason": "unknown object_id"})
            continue
        if field not in ALLOWED_PATCH_FIELDS:
            rejected.append({"operation": op, "reason": "field is not allowed"})
            continue
        by_id[object_id][field] = op.get("value")
        applied += 1
    status = "applied" if applied and not rejected else "partial" if applied else "rejected"
    return dsl, {
        "status": status,
        "applied_count": applied,
        "rejected": rejected,
    }


def run_professional_repair_rounds(
    reference_path: str | Path,
    out: str | Path,
    dsl: dict[str, Any],
    repair_rounds: int = 0,
    repair_adapter: Callable[[str | Path, str | Path | None, dict[str, Any], int], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rounds: list[dict[str, Any]] = []
    max_rounds = max(0, int(repair_rounds))
    for idx in range(1, max_rounds + 1):
        preview = Path(out) / "rebuild_preview.png"
        patch_report = {"status": "skipped", "reason": "no repair adapter configured"}
        if repair_adapter:
            try:
                patch = repair_adapter(reference_path, preview if preview.exists() else None, dsl, idx)
                write_json(Path(out) / f"professional_repair_round_{idx}_patch.json", patch)
                dsl, patch_report = apply_professional_dsl_patch(dsl, patch if isinstance(patch, dict) else {})
            except Exception as exc:
                patch_report = {"status": "failed", "reason": str(exc), "applied_count": 0}
        report = {
            "summary": "Professional repair round report.",
            "round": idx,
            "status": patch_report.get("status"),
            "reason": patch_report.get("reason"),
            "applied_count": patch_report.get("applied_count", 0),
            "rejected": patch_report.get("rejected", []),
            "reference": str(reference_path),
            "preview": str(preview) if preview.exists() else None,
            "allowed_patch_fields": sorted(ALLOWED_PATCH_FIELDS),
        }
        write_json(Path(out) / f"professional_repair_round_{idx}.json", report)
        if int(report.get("applied_count") or 0) > 0:
            write_json(Path(out) / "professional_rebuild_script.dsl.json", dsl)
        rounds.append(report)
    return rounds


def vlm_professional_repair_adapter(reference_path: str | Path, preview_path: str | Path | None, dsl: dict[str, Any], round_index: int) -> dict[str, Any]:
    if not preview_path:
        return {"summary": "No preview available for VLM repair.", "operations": []}
    from .vlm_client import call_vlm_json, resolve_vlm_model

    model = resolve_vlm_model("RFS_PROFESSIONAL_REPAIR_MODEL", "RFS_PROFESSIONAL_REBUILD_MODEL", "MODEL_VLM")
    prompt = f"""
You are repairing a controlled Figure DSL for an editable PowerPoint rebuild.
Image 1 is the original reference. Image 2 is the current PPT preview.
Only output JSON. Do not include markdown.

Allowed operation schema:
{{"operations":[{{"op":"replace","object_id":"...","field":"bbox_percent|font_size_pt|path_percent|points_px|stroke_color|stroke_width_pt|prompt_subject|background_color_hex|generation_aspect_ratio|content_fill_target","value":...,"reason":"..."}}]}}

Rules:
- Only patch objects that are visibly wrong in the preview.
- Prefer small coordinate and font-size fixes.
- Do not add new objects in this repair mode.
- Do not patch arbitrary code; only use allowed fields.
- If uncertain, return an empty operations list.

Round: {round_index}
Current DSL:
{dsl}
""".strip()
    return call_vlm_json(prompt, [reference_path, preview_path], model=model)
