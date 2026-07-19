from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from .editable_rebuild import (
    _export_preview,
    _generate_assets,
    _load_json_or_empty,
    _make_asset_specs,
    _ppt_package_counts,
    rebuild_editable,
)
from .ppt_compiler import compile_ppt
from .professional_compiler import dsl_to_program
from .professional_dsl import fallback_professional_dsl, validate_and_normalize_dsl
from .professional_gap import build_professional_gap_report
from .professional_repair import run_professional_repair_rounds
from .professional_script_planner import plan_professional_dsl, write_professional_notes
from .utils import ensure_dir, write_json


def _draw_geometry_overlay(reference: Path, out: Path, program: dict) -> None:
    image = Image.open(reference).convert("RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for panel in program.get("panels", []):
        bb = panel.get("bbox_percent") or {}
        box = [bb.get("x", 0) * w, bb.get("y", 0) * h, (bb.get("x", 0) + bb.get("w", 0)) * w, (bb.get("y", 0) + bb.get("h", 0)) * h]
        draw.rectangle(box, outline="#2368B8", width=4)
        draw.text((box[0] + 4, box[1] + 4), str(panel.get("id")), fill="#2368B8")
    for slot in program.get("slots", []):
        bb = slot.get("bbox_percent") or {}
        box = [bb.get("x", 0) * w, bb.get("y", 0) * h, (bb.get("x", 0) + bb.get("w", 0)) * w, (bb.get("y", 0) + bb.get("h", 0)) * h]
        draw.rectangle(box, outline="#D17721", width=3)
        draw.text((box[0] + 3, box[1] + 3), str(slot.get("id")), fill="#D17721")
    image.save(out / "reference_geometry_overlay.png")


def _draw_controls_overlay(reference: Path, out: Path, arrows: list[dict]) -> None:
    image = Image.open(reference).convert("RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for arrow in arrows:
        pts = arrow.get("path_percent") or []
        xy = [(float(point[0]) * w, float(point[1]) * h) for point in pts if isinstance(point, list) and len(point) >= 2]
        if len(xy) >= 2:
            color = str(arrow.get("stroke_color") or "#C33")
            draw.line(xy, fill=color, width=max(2, int(float(arrow.get("stroke_width_pt") or 2))))
            draw.text((xy[-1][0] + 3, xy[-1][1] + 3), str(arrow.get("id")), fill=color)
    image.save(out / "reference_controls_overlay.png")


def _write_contracts_from_program(out: Path, program: dict, planner_report: dict) -> None:
    geometry = {
        "summary": "Professional DSL reference geometry.",
        "layout_mode": "professional_dsl",
        "vlm_status": planner_report.get("status"),
        "canvas": program.get("canvas"),
        "palette": program.get("style", {}).get("palette", []),
        "panels": program.get("panels", []),
        "cards": program.get("cards", []),
        "slots": program.get("slots", []),
        "legend_regions": program.get("labels", []),
    }
    write_json(out / "reference_geometry.json", geometry)
    write_json(out / "reference_text_geometry.json", {
        "summary": "Professional DSL editable text geometry.",
        "detection_mode": "professional_dsl",
        "text_regions": program.get("text_program", {}).get("items", []),
    })
    write_json(out / "ocr_text_quality_report.json", {
        "summary": "Professional DSL text quality report.",
        "mode": "professional_dsl",
        "status": "generated",
        "text_count": len(program.get("text_program", {}).get("items", [])),
    })
    write_json(out / "slot_semantic_report.json", {
        "summary": "Professional DSL semantic report.",
        "semantic_vlm_status": planner_report.get("status"),
        "slots": [{
            "slot_id": slot.get("id"),
            "asset_type": slot.get("asset_type"),
            "semantic_role": slot.get("semantic_role"),
            "prompt_subject": slot.get("prompt_subject"),
            "nearby_text": slot.get("nearby_text", []),
        } for slot in program.get("slots", [])],
    })


def _compile_professional(
    reference_path: Path,
    archived_reference: Path,
    out: Path,
    dsl: dict,
    planner_report: dict,
    asset_mode: str,
    asset_workers: int,
    asset_retries: int,
    economy_mode: bool,
    regenerate_slots: str | list[str] | None,
    strict_asset_regeneration: bool,
    export_preview: bool,
    generate_assets: bool = True,
    baseline_program: dict | None = None,
    benchmark_out: str | Path | None = None,
) -> dict:
    normalized, validation = validate_and_normalize_dsl(dsl, archived_reference, out)
    write_json(out / "professional_rebuild_script.dsl.json", normalized)
    write_json(out / "professional_rebuild_plan.json", {
        "summary": "Professional rebuild plan generated before DSL interpretation.",
        "planner_report": planner_report,
        "dsl_summary": normalized.get("summary"),
        "planner": normalized.get("planner"),
        "object_count": len(normalized.get("objects", [])),
    })
    write_professional_notes(out, planner_report, validation)
    if validation["status"] == "error":
        return {
            "summary": "Professional rebuild DSL validation failed.",
            "ok": False,
            "out_dir": str(out),
            "reference": str(reference_path),
            "validation": validation,
        }

    program = dsl_to_program(normalized, out)
    gap_report = build_professional_gap_report(out, baseline_program, program, benchmark_out=benchmark_out)
    _write_contracts_from_program(out, program, planner_report)
    _draw_geometry_overlay(archived_reference, out, program)
    _draw_controls_overlay(archived_reference, out, program.get("arrows", []))

    specs = _make_asset_specs(program, archived_reference, out)
    write_json(out / "asset_generation_specs.json", {"summary": "Professional DSL slot-level asset generation specs.", "asset_mode": asset_mode, "specs": specs})
    regen: set[str] = set()
    if isinstance(regenerate_slots, str):
        regen = {item.strip() for item in regenerate_slots.split(",") if item.strip()}
    elif isinstance(regenerate_slots, list):
        regen = {str(item).strip() for item in regenerate_slots if str(item).strip()}
    if generate_assets:
        asset_reports, asset_summary = _generate_assets(specs, program, out, asset_mode, asset_workers, asset_retries, economy_mode, regen, strict_asset_regeneration)
    else:
        program["assets"] = [{"id": spec["asset_id"], "path": f"assets/{spec['asset_id']}.png", "source": "slot_asset"} for spec in specs]
        existing_report = _load_json_or_empty(out / "asset_generation_report.json")
        asset_reports = existing_report.get("assets", []) if isinstance(existing_report.get("assets"), list) else []
        asset_summary = {
            "summary": "Asset generation skipped by professional --compile-only.",
            "asset_mode": asset_mode,
            "api_requests_attempted": 0,
            "assets": asset_reports,
        }
        write_json(out / "asset_generation_report.json", asset_summary)
        write_json(out / "asset_economy_report.json", {
            "summary": "Asset economy skipped by professional --compile-only.",
            "api_requests_attempted": 0,
        })
    write_json(out / "figure_program.json", program)
    pptx_path = compile_ppt(program, out)
    preview = _export_preview(pptx_path, out) if export_preview else None
    counts = _ppt_package_counts(pptx_path, archived_reference)
    write_json(out / "composition_quality_report.json", {
        "summary": "Professional editable rebuild composition quality report.",
        "professional_rebuild_summary": counts,
        "rebuild_editable_summary": counts,
        "dsl_validation": validation,
        "asset_count": len(asset_reports),
        "professional_gap_report": gap_report,
        "no_full_image_policy": {
            "status": "pass",
            "contains_full_reference_image": False,
            "policy": "reference image is archived only; final PPT uses DSL objects and slot assets",
        },
    })
    return {
        "summary": "Professional image-to-editable-PPT rebuild complete.",
        "ok": True,
        "out_dir": str(out),
        "reference": str(reference_path),
        "pptx": str(pptx_path),
        "preview": str(preview) if preview else None,
        "asset_mode": asset_mode,
        "asset_workers": asset_workers,
        "asset_retries": asset_retries,
        "economy_mode": economy_mode,
        "api_requests_attempted": asset_summary.get("api_requests_attempted", 0),
        "asset_count": len(asset_reports),
        "slot_count": len(program.get("slots", [])),
        "text_count": len(program.get("text_program", {}).get("items", [])),
        "connector_count": len(program.get("arrows", [])),
        "layout_mode": "professional_dsl",
        "control_mode": "professional_dsl",
        "professional_mode": True,
        "reports": {
            "professional_rebuild_plan": str(out / "professional_rebuild_plan.json"),
            "professional_rebuild_script": str(out / "professional_rebuild_script.dsl.json"),
            "professional_rebuild_validation": str(out / "professional_rebuild_validation.json"),
            "professional_rebuild_notes": str(out / "professional_rebuild_notes.md"),
            "figure_program": str(out / "figure_program.json"),
            "composition_quality_report": str(out / "composition_quality_report.json"),
            "professional_gap_report": str(out / "professional_gap_report.json"),
        },
    }


def rebuild_editable_pro(
    reference: str | Path,
    out: str | Path,
    asset_mode: str = "api",
    asset_workers: int = 4,
    asset_retries: int = 1,
    economy_mode: bool = True,
    text_mode: str = "ocr",
    control_mode: str = "hybrid",
    layout_mode: str = "hybrid",
    export_preview: bool = False,
    regenerate_slots: str | list[str] | None = None,
    strict_asset_regeneration: bool = False,
    compile_only: bool = False,
    repair_rounds: int = 2,
    ocr_engine: str = "paddle",
    ocr_lang: str = "en_ch",
    vlm_layout_adapter: Callable | None = None,
    control_adapter: Callable | None = None,
    semantic_adapter: Callable | None = None,
    planner_adapter: Callable | None = None,
    repair_adapter: Callable | None = None,
    benchmark_out: str | Path | None = None,
) -> dict:
    reference_path = Path(reference)
    if not reference_path.exists():
        raise FileNotFoundError(reference_path)
    out_path = ensure_dir(out)
    input_dir = ensure_dir(out_path / "inputs")
    archived_reference = input_dir / reference_path.name
    if not archived_reference.exists() or not archived_reference.samefile(reference_path):
        shutil.copyfile(reference_path, archived_reference)
    write_json(out_path / "input_manifest.json", {
        "summary": "Input manifest for professional scripted editable rebuild.",
        "reference": str(reference_path),
        "archived_reference": str(archived_reference),
        "asset_mode": asset_mode,
        "text_mode": text_mode,
        "control_mode": control_mode,
        "layout_mode": layout_mode,
        "compile_only": compile_only,
        "repair_rounds": repair_rounds,
        "benchmark_out": str(benchmark_out) if benchmark_out else None,
    })

    if compile_only:
        dsl_path = out_path / "professional_rebuild_script.dsl.json"
        if not dsl_path.exists():
            raise FileNotFoundError(dsl_path)
        dsl = json.loads(dsl_path.read_text(encoding="utf-8"))
        planner_report = {"status": "compile_only", "mode": "existing_professional_dsl"}
        result = _compile_professional(
            reference_path,
            archived_reference,
            out_path,
            dsl,
            planner_report,
            asset_mode,
            asset_workers,
            asset_retries,
            economy_mode,
            regenerate_slots,
            strict_asset_regeneration,
            export_preview,
            generate_assets=False,
            baseline_program=None,
            benchmark_out=benchmark_out,
        )
        result["compile_only"] = True
        write_json(out_path / "rebuild_result.json", result)
        return result

    baseline_result = rebuild_editable(
        reference_path,
        out_path,
        asset_mode="placeholder",
        asset_workers=1,
        asset_retries=0,
        economy_mode=True,
        text_mode=text_mode,
        control_mode=control_mode,
        layout_mode=layout_mode,
        export_preview=False,
        regenerate_slots=None,
        strict_asset_regeneration=False,
        skip_analysis=False,
        compile_only=False,
        ocr_engine=ocr_engine,
        ocr_lang=ocr_lang,
        vlm_layout_adapter=vlm_layout_adapter,
        control_adapter=control_adapter,
        semantic_adapter=semantic_adapter,
    )
    baseline_program = _load_json_or_empty(out_path / "figure_program.json")
    if not baseline_program:
        baseline_program = fallback_professional_dsl(archived_reference)
    text_geometry = _load_json_or_empty(out_path / "reference_text_geometry.json")
    dsl, planner_report = plan_professional_dsl(archived_reference, baseline_program, text_geometry, planner_adapter=planner_adapter)
    planner_report["baseline"] = {
        "slot_count": baseline_result.get("slot_count"),
        "text_count": baseline_result.get("text_count"),
        "connector_count": baseline_result.get("connector_count"),
    }
    result = _compile_professional(
        reference_path,
        archived_reference,
        out_path,
        dsl,
        planner_report,
        asset_mode,
        asset_workers,
        asset_retries,
        economy_mode,
        regenerate_slots,
        strict_asset_regeneration,
        export_preview,
        baseline_program=baseline_program,
        benchmark_out=benchmark_out,
    )
    repair_reports = run_professional_repair_rounds(archived_reference, out_path, dsl, repair_rounds=repair_rounds, repair_adapter=repair_adapter)
    if any(int(item.get("applied_count") or 0) > 0 for item in repair_reports):
        patched_dsl = json.loads((out_path / "professional_rebuild_script.dsl.json").read_text(encoding="utf-8"))
        result = _compile_professional(
            reference_path,
            archived_reference,
            out_path,
            patched_dsl,
            {**planner_report, "repair_status": "patched"},
            asset_mode,
            asset_workers,
            asset_retries,
            economy_mode,
            regenerate_slots,
            strict_asset_regeneration,
            export_preview,
            baseline_program=baseline_program,
            benchmark_out=benchmark_out,
        )
    result["repair_rounds"] = len(repair_reports)
    result["planner_status"] = planner_report.get("status")
    write_json(out_path / "rebuild_result.json", result)
    return result
