from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from ..utils import ensure_dir, write_json, write_text
from .analyzer import paper_markdown, parse_paper
from .planner import compile_image_prompt, merge_preferences, plan_paper_image, validate_plan_grounding
from .review import build_paper_review, detect_domain_profile, validate_review_coverage


def _load_preferences(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Preferences file does not exist: {source}")
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Preferences file must contain a JSON object")
    return raw


def _archive_file(source: str | Path, target_dir: Path, target_name: str | None = None) -> str:
    path = Path(source).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (target_name or path.name)
    if target.resolve() != path:
        shutil.copyfile(path, target)
    return str(target)


def _section_summary_markdown(parsed: dict[str, Any]) -> str:
    grouped: dict[str, list[str]] = {}
    for item in parsed.get("evidence", []):
        section = str(item.get("section_hint") or "Unclassified")
        grouped.setdefault(section, []).append(str(item.get("text") or ""))
    lines = ["# Section Summary", ""]
    for section, values in grouped.items():
        combined = " ".join(value.replace("\n", " ") for value in values)
        sentences = [value.strip() for value in combined.split(". ") if value.strip()]
        summary = ". ".join(sentences[:3])[:900].strip()
        lines.extend([f"## {section}", "", summary or "No reliable summary extracted.", ""])
    return "\n".join(lines).strip() + "\n"


def _collect_evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_ids" and isinstance(child, list):
                found.update(str(item) for item in child if str(item).strip())
            else:
                found.update(_collect_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_evidence_ids(child))
    return found


def _item_id(item: dict[str, Any], field: str, index: int) -> str:
    return str(item.get("id") or item.get("name") or item.get("visible_label") or item.get("text") or item.get("statement") or f"{field}_{index}").strip()


def _item_label(item: dict[str, Any]) -> str:
    return str(item.get("visible_label") or item.get("name") or item.get("text") or item.get("statement") or item.get("label") or item.get("id") or "").strip()


def _infer_topology(spec: dict[str, Any]) -> str:
    relations = [item for item in spec.get("relations", []) if isinstance(item, dict)]
    if any("feedback" in str(item.get("type") or "").casefold() for item in relations):
        return "feedback"
    inputs = [item for item in spec.get("inputs", []) if isinstance(item, dict)]
    labels = " ".join(_item_label(item).casefold() for item in inputs)
    modalities = sum(term in labels for term in ("image", "text", "audio", "video", "depth", "thermal", "imu"))
    if len(inputs) >= 3 or modalities >= 3:
        return "multimodal"
    outgoing: dict[str, int] = {}
    for relation in relations:
        source = str(relation.get("source") or relation.get("source_id") or "")
        outgoing[source] = outgoing.get(source, 0) + 1
    if any(value > 1 for value in outgoing.values()):
        return "branch"
    total = sum(len(spec.get(field, []) if isinstance(spec.get(field), list) else []) for field in ("inputs", "modules", "outputs", "innovations"))
    if total >= 12:
        return "dense_multiframe"
    return "linear" if relations else "unknown"


def normalize_figure_contract(plan: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("paper_summary") if isinstance(plan.get("paper_summary"), dict) else {}
    spec = plan.get("figure_specification") if isinstance(plan.get("figure_specification"), dict) else {}
    spec.setdefault("research_problem", summary.get("research_problem") or {"text": "unknown", "evidence_ids": []})
    spec.setdefault("central_claim", summary.get("central_claim") or {"text": "unknown", "evidence_ids": []})
    if not isinstance(spec.get("inputs"), list) or not spec.get("inputs"):
        spec["inputs"] = summary.get("inputs") if isinstance(summary.get("inputs"), list) else []
    if not isinstance(spec.get("outputs"), list) or not spec.get("outputs"):
        spec["outputs"] = summary.get("outputs") if isinstance(summary.get("outputs"), list) else []
    spec.setdefault("training_flow", summary.get("training_flow") if isinstance(summary.get("training_flow"), list) else [])
    spec.setdefault("inference_flow", summary.get("inference_flow") if isinstance(summary.get("inference_flow"), list) else [])
    spec.setdefault("feedback_loops", [item for item in spec.get("relations", []) if isinstance(item, dict) and "feedback" in str(item.get("type") or "").casefold()])
    spec.setdefault("topology", _infer_topology(spec))
    labels = []
    terminology = spec.get("terminology") if isinstance(spec.get("terminology"), dict) else {}
    labels.extend(str(value).strip() for value in terminology.values() if str(value).strip())
    for field in ("inputs", "modules", "outputs", "innovations"):
        for item in spec.get(field, []) if isinstance(spec.get(field), list) else []:
            if isinstance(item, dict) and _item_label(item):
                labels.append(_item_label(item))
    spec["required_labels"] = list(dict.fromkeys(labels))
    raw_uncertainties = list(summary.get("unknowns", []) if isinstance(summary.get("unknowns"), list) else [])
    uncertainties = [
        str(item.get("statement") or item.get("text") or item.get("id") or "unknown") if isinstance(item, dict) else str(item)
        for item in raw_uncertainties
    ]
    evidence_by_id = {item["id"]: item for item in parsed.get("evidence", [])}
    for field in ("inputs", "modules", "outputs", "relations", "innovations"):
        for item in spec.get(field, []) if isinstance(spec.get(field), list) else []:
            if not isinstance(item, dict):
                continue
            evidence = [evidence_by_id.get(value) for value in item.get("evidence_ids", [])]
            valid_records = [record for record in evidence if record]
            if valid_records and all(float(record.get("confidence", 1.0)) < 0.75 and str(record.get("source") or "").casefold() in {"easyocr", "paddle", "adapter"} for record in valid_records):
                uncertainties.append(f"{_item_id(item, field, 0)} relies only on low-confidence OCR evidence")
    spec["uncertainties"] = list(dict.fromkeys(str(item) for item in uncertainties if str(item).strip()))
    spec.setdefault("forbidden_inventions", [])
    plan["figure_specification"] = spec
    return spec


def build_overlay_spec(plan: dict[str, Any]) -> dict[str, Any]:
    spec = plan.get("figure_specification", {})
    labels = []
    for field in ("inputs", "modules", "outputs", "innovations"):
        for index, item in enumerate(spec.get(field, []) if isinstance(spec.get(field), list) else []):
            if not isinstance(item, dict):
                continue
            text = _item_label(item)
            if text:
                labels.append({"target_id": _item_id(item, field, index), "text": text, "role": field.rstrip("s")})
    connectors = []
    for item in spec.get("relations", []) if isinstance(spec.get("relations"), list) else []:
        if isinstance(item, dict):
            connectors.append({
                "source": str(item.get("source") or item.get("source_id") or ""),
                "target": str(item.get("target") or item.get("target_id") or ""),
                "type": str(item.get("type") or item.get("relation_type") or "data_flow"),
                "label": str(item.get("label") or ""),
            })
    return {
        "summary": "Exact editable labels and directed connectors derived from the paper contract.",
        "labels": labels,
        "connectors": connectors,
        "groups": list(plan.get("design_plan", {}).get("groups", []) if isinstance(plan.get("design_plan"), dict) else []),
        "reading_order": list(plan.get("design_plan", {}).get("reading_order", []) if isinstance(plan.get("design_plan"), dict) else []),
    }


def prepare_paper_figure_contract(
    paper: str | Path,
    out: str | Path,
    deadline_seconds: int = 180,
    planner_mode: str = "vlm",
    planner_model: str | None = None,
    ocr_engine: str = "auto",
    ocr_lang: str = "en_ch",
    preferences_path: str | Path | None = None,
    positive_references: list[str] | None = None,
    negative_references: list[str] | None = None,
    aspect_ratio: str | None = None,
    language: str | None = None,
    domain_profile: str = "auto",
    ocr_adapter: Callable | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    root = ensure_dir(out).resolve()
    inputs = ensure_dir(root / "inputs")
    positive_dir = ensure_dir(inputs / "positive_references")
    negative_dir = ensure_dir(inputs / "negative_references")
    archived_paper = _archive_file(paper, inputs, f"paper{Path(paper).suffix.lower()}")
    archived_positive = [_archive_file(path, positive_dir) for path in (positive_references or [])]
    archived_negative = [_archive_file(path, negative_dir) for path in (negative_references or [])]
    raw_preferences = _load_preferences(preferences_path)
    preferences = merge_preferences(raw_preferences, aspect_ratio=aspect_ratio, language=language)
    preferences["positive_references"] = archived_positive
    preferences["negative_references"] = archived_negative
    write_json(root / "preferences.json", preferences)
    write_json(root / "input_manifest.json", {
        "summary": "Archived inputs for paper figure contract preparation.",
        "paper_original": str(Path(paper).resolve()),
        "paper_archived": archived_paper,
        "preferences_original": str(Path(preferences_path).resolve()) if preferences_path else None,
        "positive_references": archived_positive,
        "negative_references": archived_negative,
    })

    deadline = max(30, int(deadline_seconds))
    deadline_at = started + deadline
    parsed = parse_paper(archived_paper, deadline_at=deadline_at, ocr_engine=ocr_engine, ocr_lang=ocr_lang, ocr_adapter=ocr_adapter)
    write_json(root / "document_model.json", parsed)
    write_json(root / "extraction_report.json", parsed["extraction_report"])
    write_json(root / "document_index.json", parsed["document_index"])
    write_json(root / "section_index.json", parsed["document_index"])
    write_json(root / "evidence_map.json", {"summary": "Page-aware evidence map.", "source_path": parsed["source_path"], "page_count": parsed["page_count"], "char_count": parsed["char_count"], "headings": parsed["headings"], "evidence": parsed["evidence"]})
    write_text(root / "paper.md", paper_markdown(parsed))
    write_text(root / "section_summary.md", _section_summary_markdown(parsed))

    if parsed["extraction_report"].get("status") == "fail":
        result = {
            "summary": "Paper extraction failed the minimum readable-page gate.",
            "ok": False,
            "status": "extraction_failed",
            "out_dir": str(root),
            "paper": archived_paper,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "errors": parsed["extraction_report"].get("warnings", []),
        }
        write_json(root / "run_report.json", result)
        return {**result, "root": root, "parsed": parsed, "preferences": preferences}

    selected_domain = detect_domain_profile(parsed, explicit=domain_profile)
    write_json(root / "domain_profile.json", selected_domain)
    remaining = max(10, int(deadline_at - time.monotonic() - 15))
    effective_mode = planner_mode if remaining >= 30 else "heuristic"
    paper_review, review_metadata = build_paper_review(parsed, selected_domain, mode=effective_mode, model=planner_model, timeout_seconds=min(75, remaining), retries=0)
    review_prompt = review_metadata.pop("prompt")
    write_text(root / "prompts" / "paper_review_prompt.txt", review_prompt)
    write_json(root / "paper_review_metadata.json", review_metadata)
    write_json(root / "paper_review.json", paper_review)
    coverage = validate_review_coverage(paper_review, parsed, selected_domain, strict=False)
    write_json(root / "review_coverage_report.json", coverage)

    remaining = max(10, int(deadline_at - time.monotonic() - 15))
    planning_mode = effective_mode if remaining >= 25 else "heuristic"
    plan, planner_metadata = plan_paper_image(
        parsed,
        preferences,
        mode=planning_mode,
        model=planner_model,
        reference_images=archived_positive + archived_negative,
        paper_review=paper_review,
        timeout_seconds=min(70, remaining),
        retries=0,
    )
    planning_prompt = planner_metadata.pop("prompt")
    write_text(root / "prompts" / "planning_prompt.txt", planning_prompt)
    write_json(root / "planning_metadata.json", {"summary": "Planner execution metadata.", **planner_metadata})
    normalize_figure_contract(plan, parsed)
    for name in ("paper_summary", "figure_specification", "design_plan", "layout_intent", "visual_metaphors", "style_plan"):
        write_json(root / f"{name}.json", plan[name])
    planning_validation = validate_plan_grounding(plan, parsed)
    write_json(root / "planning_validation_report.json", planning_validation)
    overlay = build_overlay_spec(plan)
    write_json(root / "overlay_spec.json", overlay)
    final_prompt = compile_image_prompt(plan, preferences, candidate_variant=1)
    write_text(root / "image_prompt.md", final_prompt)
    write_text(root / "image_prompt.txt", final_prompt)
    referenced_ids = _collect_evidence_ids({"paper_review": paper_review, "figure_specification": plan["figure_specification"]})
    write_json(root / "key_evidence.json", {
        "summary": "Evidence records referenced by the paper review and figure contract.",
        "evidence": [item for item in parsed["evidence"] if item["id"] in referenced_ids],
    })

    elapsed = round(time.monotonic() - started, 3)
    deadline_reached = time.monotonic() >= deadline_at
    production_ready = bool(
        review_metadata.get("mode") == "vlm"
        and planner_metadata.get("mode") == "vlm"
        and planning_validation.get("ok")
        and not deadline_reached
    )
    status = "complete" if production_ready else "completed_with_warnings"
    result = {
        "summary": "Fast paper-to-framework contract preparation completed.",
        "ok": bool(planning_validation.get("ok")),
        "status": status,
        "production_ready": production_ready,
        "engineering_only": not production_ready,
        "out_dir": str(root),
        "paper": archived_paper,
        "source_sha256": parsed["source_sha256"],
        "deadline_seconds": deadline,
        "deadline_reached": deadline_reached,
        "elapsed_seconds": elapsed,
        "planner_mode": planner_metadata.get("mode"),
        "paper_review_mode": review_metadata.get("mode"),
        "planner_warning": planner_metadata.get("warning"),
        "review_warning": review_metadata.get("warning"),
        "topology": plan["figure_specification"].get("topology"),
        "module_count": len(plan["figure_specification"].get("modules", [])),
        "relation_count": len(plan["figure_specification"].get("relations", [])),
        "uncertainties": plan["figure_specification"].get("uncertainties", []),
        "artifacts": ["paper.md", "document_model.json", "extraction_report.json", "section_index.json", "section_summary.md", "key_evidence.json", "paper_review.json", "figure_specification.json", "planning_validation_report.json", "image_prompt.md", "overlay_spec.json", "run_report.json"],
    }
    write_json(root / "run_report.json", result)
    return {
        **result,
        "root": root,
        "parsed": parsed,
        "preferences": preferences,
        "paper_review": paper_review,
        "review_metadata": review_metadata,
        "selected_domain": selected_domain,
        "plan": plan,
        "planner_metadata": planner_metadata,
        "archived_positive": archived_positive,
        "archived_negative": archived_negative,
        "planning_validation": planning_validation,
    }


def run_fast_framework_prompt(**kwargs: Any) -> dict[str, Any]:
    prepared = prepare_paper_figure_contract(**kwargs)
    internal = {"root", "parsed", "preferences", "paper_review", "review_metadata", "selected_domain", "plan", "planner_metadata", "archived_positive", "archived_negative", "planning_validation"}
    return {key: value for key, value in prepared.items() if key not in internal}
