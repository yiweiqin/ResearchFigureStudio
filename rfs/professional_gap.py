from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import write_json


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _program_counts(program: dict[str, Any]) -> dict[str, int]:
    text_program = program.get("text_program") if isinstance(program.get("text_program"), dict) else {}
    return {
        "panel_count": len(program.get("panels", []) or []),
        "card_count": len(program.get("cards", []) or []),
        "slot_count": len(program.get("slots", []) or []),
        "asset_count": len(program.get("assets", []) or []),
        "connector_count": len(program.get("arrows", []) or []),
        "text_count": len(text_program.get("items", []) or []),
        "legend_count": len(program.get("labels", []) or []),
    }


def _counts_from_output(out: Path) -> dict[str, int]:
    program = _read_json(out / "figure_program.json")
    if program:
        return _program_counts(program)
    quality = _read_json(out / "composition_quality_report.json")
    summary = quality.get("rebuild_editable_summary") or quality.get("professional_rebuild_summary") or {}
    return {
        "panel_count": 0,
        "card_count": 0,
        "slot_count": 0,
        "asset_count": int(summary.get("picture_count") or 0),
        "connector_count": int(summary.get("connector_count") or 0),
        "text_count": int(summary.get("text_shape_count") or 0),
        "legend_count": 0,
    }


def build_professional_gap_report(
    out: str | Path,
    baseline_program: dict[str, Any] | None,
    pro_program: dict[str, Any],
    benchmark_out: str | Path | None = None,
) -> dict[str, Any]:
    out_path = Path(out)
    baseline_counts = _program_counts(baseline_program or {})
    pro_counts = _program_counts(pro_program)
    benchmark_counts = _counts_from_output(Path(benchmark_out)) if benchmark_out else None

    def delta(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
        keys = sorted(set(left) | set(right))
        return {key: int(left.get(key, 0)) - int(right.get(key, 0)) for key in keys}

    risks: list[str] = []
    if pro_counts["text_count"] <= baseline_counts["text_count"] and baseline_counts["text_count"] > 0:
        risks.append("professional_text_count_not_higher_than_baseline")
    if pro_counts["connector_count"] < baseline_counts["connector_count"]:
        risks.append("professional_connector_count_lower_than_baseline")
    if benchmark_counts:
        if pro_counts["text_count"] < benchmark_counts.get("text_count", 0):
            risks.append("professional_text_count_below_benchmark")
        if pro_counts["connector_count"] < benchmark_counts.get("connector_count", 0):
            risks.append("professional_connector_count_below_benchmark")

    report = {
        "summary": "Professional rebuild gap report comparing baseline contracts, professional DSL output, and optional specialized benchmark output.",
        "status": "warning" if risks else "pass",
        "baseline_counts": baseline_counts,
        "professional_counts": pro_counts,
        "professional_minus_baseline": delta(pro_counts, baseline_counts),
        "benchmark_out": str(benchmark_out) if benchmark_out else None,
        "benchmark_counts": benchmark_counts,
        "professional_minus_benchmark": delta(pro_counts, benchmark_counts) if benchmark_counts else None,
        "risks": risks,
        "recommended_next_actions": [
            "Add/adjust few-shot DSL examples if text or connector counts lag the specialized benchmark.",
            "Inspect professional_rebuild_script.dsl.json before spending image-generation API credits.",
            "Use --compile-only after manual DSL edits to avoid rerunning VLM planning or asset generation.",
        ],
    }
    write_json(out_path / "professional_gap_report.json", report)
    return report
