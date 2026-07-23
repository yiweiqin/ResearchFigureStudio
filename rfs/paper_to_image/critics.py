from __future__ import annotations

import os
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from ..reference_text_extractor import run_easyocr, run_paddle_ocr, run_rapidocr
from ..vlm_client import call_vlm_json, resolve_vlm_model, vlm_credentials_available
from .planner import collect_visible_labels, collect_visual_relations


def _normalize_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def _issue_text(value: object) -> str:
    if not isinstance(value, dict):
        return str(value).strip()
    source = str(value.get("source") or value.get("source_label") or "").strip()
    target = str(value.get("target") or value.get("target_label") or "").strip()
    status = str(value.get("status") or value.get("type") or "").strip()
    evidence = str(value.get("visible_evidence") or value.get("reason") or "").strip()
    relation = f"{source} -> {target}" if source or target else "connector issue"
    details = ": ".join(part for part in (status, evidence) if part)
    return f"{relation}: {details}" if details else relation


def required_labels(plan: dict) -> list[str]:
    return collect_visible_labels(plan.get("figure_specification", {}))


def _local_ocr(path: Path, engine: str, lang: str, adapter: Callable | None = None) -> tuple[list[dict], str, str | None]:
    try:
        if adapter:
            records = adapter(path, lang)
            return records, "adapter", None
        if engine == "rapidocr":
            return run_rapidocr(path, lang), "rapidocr", None
        if engine == "easyocr":
            return run_easyocr(path, lang), "easyocr", None
        if engine == "paddle":
            return run_paddle_ocr(path, lang), "paddle", None
    except Exception as exc:
        return [], engine, str(exc)
    return [], engine, "local OCR disabled"


def _vlm_critic(path: Path, blueprint: Path, plan: dict, template: dict, labels: list[str], repeatable_labels: list[str], forbidden_labels: list[str], model: str | None, adapter: Callable | None = None) -> dict:
    prompt = f"""
# Summary

Act as a strict production critic for a scientific framework image. The first image is the generated candidate; the second is a content-free layout blueprint. Return JSON only.

Required exact labels:
{json.dumps(labels, ensure_ascii=False)}

Evidence-supported labels that may repeat to show reuse of the same component:
{json.dumps(repeatable_labels, ensure_ascii=False)}

Forbidden copied reference labels:
{json.dumps(forbidden_labels, ensure_ascii=False)}

Scientific specification:
{json.dumps(plan.get('figure_specification', {}), ensure_ascii=False, indent=2)}

Mandatory visual connector checklist:
{json.dumps(collect_visual_relations(plan.get('figure_specification', {})), ensure_ascii=False, indent=2)}

Judge the visible flow against the mandatory visual connector checklist. Relations involving an evidence-supported repeatable shared component may be represented by repeated badges rather than extra implementation-level arrows. A shortcut that bypasses a checklist module is a scientific error.

Selected template:
{json.dumps({key: template.get(key) for key in ['template_id', 'panels', 'connectors', 'visual_density', 'style']}, ensure_ascii=False, indent=2)}

Template interpretation rule: panels are macro spatial regions and role guides, not an exact required count of scientific content nodes. Do not report a template mismatch merely because multiple paper-grounded nodes appear inside one macro region. Judge reading order, spatial roles, connector rhythm, and the required feedback topology.

Return:
{{
  "summary": "Production candidate review.",
  "ocr": {{"detected_labels": [], "missing_labels": [], "misspelled_labels": [], "duplicate_labels": [], "forbidden_labels_found": [], "score": 0.0, "passed": false}},
  "scientific": {{"missing_modules": [], "missing_relations": [], "reversed_relations": [], "invented_items": [], "innovation_visible": true, "score": 0.0, "passed": false}},
  "template": {{"macro_panel_match": 0.0, "reading_order_match": 0.0, "connector_rhythm_match": 0.0, "visual_density_match": 0.0, "copied_reference_content": [], "score": 0.0, "passed": false}},
  "aesthetic": {{"hierarchy": 0.0, "balance": 0.0, "whitespace": 0.0, "color": 0.0, "icon_consistency": 0.0, "readability": 0.0, "score": 0.0, "passed": false}},
  "preserve": [],
  "repair": [],
  "remove": [],
  "repair_regions": [],
  "hard_errors": [],
  "production_pass": false,
  "overall_score": 0.0
}}

Hard failures: any missing/misspelled critical label, any duplicate label not explicitly allowed above, copied reference term, missing core module, reversed relation, invented mechanism, or template score below 0.72. Aesthetic quality cannot compensate for scientific or OCR failure.
""".strip()
    if adapter:
        return adapter(path, blueprint, prompt)
    resolved = resolve_vlm_model("RFS_PAPER_TO_IMAGE_REVIEW_MODEL", "RFS_CRITIC_MODEL", explicit_model=model)
    timeout = max(15, int(os.getenv("RFS_PAPER_TO_IMAGE_REVIEW_TIMEOUT", "90")))
    raw = call_vlm_json(prompt, [path, blueprint], model=resolved, timeout=timeout, retries=0)
    raw.setdefault("summary", "Production candidate review.")
    raw["model"] = resolved
    return raw


def _normalize_section(raw: Any, name: str) -> dict:
    section = raw if isinstance(raw, dict) else {}
    section.setdefault("summary", f"{name} review.")
    try:
        score = float(section.get("score", 0.0))
        if 1.0 < score <= 10.0:
            score /= 10.0
        elif 10.0 < score <= 100.0:
            score /= 100.0
        section["score"] = max(0.0, min(1.0, score))
    except Exception:
        section["score"] = 0.0
    section["passed"] = bool(section.get("passed", False))
    return section


def _vlm_topology_critic(path: Path, plan: dict, model: str | None, adapter: Callable | None = None) -> dict:
    relations = collect_visual_relations(plan.get("figure_specification", {}))
    prompt = f"""
# Summary

Act as a focused topology verifier for one scientific framework image. Inspect visible connector paths and arrowheads rather than inferring the intended method. Return JSON only.

Mandatory directed connectors:
{json.dumps(relations, ensure_ascii=False, indent=2)}

Rules:
- Verify every source, target, and arrowhead direction from visible geometry.
- A line that joins the outgoing side of a target or a downstream junction does not count as entering that target.
- A shortcut that bypasses an intermediate module is an invented relation.
- For refinement loops, Initial Output and Self-Feedback must both enter Refine or its explicit input-side shared-model node before Refined Output.
- Refined Output must return to Feedback to close the loop.
- Do not penalize repeated labels explicitly allowed by the scientific contract.

Return:
{{
  "summary": "Focused visible-connector verification.",
  "relations": [{{"source": "...", "target": "...", "status": "present|missing|reversed|bypassed", "visible_evidence": "..."}}],
  "missing_relations": [],
  "reversed_relations": [],
  "bypassed_relations": [],
  "invented_relations": [],
  "repair": [],
  "repair_regions": [],
  "score": 0.0,
  "passed": false
}}
""".strip()
    if adapter:
        return adapter(path, prompt)
    resolved = resolve_vlm_model("RFS_PAPER_TO_IMAGE_TOPOLOGY_MODEL", "RFS_FROZEN_JUDGE_MODEL", explicit_model=model)
    timeout = max(15, int(os.getenv("RFS_PAPER_TO_IMAGE_TOPOLOGY_TIMEOUT", "90")))
    result = call_vlm_json(prompt, [path], model=resolved, timeout=timeout, retries=0)
    result.setdefault("summary", "Focused visible-connector verification.")
    result["model"] = resolved
    return result


def review_candidate(
    path: str | Path,
    blueprint: str | Path,
    plan: dict,
    template: dict,
    mode: str = "vlm",
    model: str | None = None,
    ocr_engine: str = "auto",
    ocr_lang: str = "en_ch",
    ocr_adapter: Callable | None = None,
    critic_adapter: Callable | None = None,
    topology_adapter: Callable | None = None,
    acceptable_aspect_ratios: list[str] | None = None,
) -> dict:
    candidate = Path(path)
    blueprint_path = Path(blueprint)
    labels = required_labels(plan)
    repeatable_labels = [str(value).strip() for value in plan.get("figure_specification", {}).get("repeatable_labels", []) if str(value).strip()]
    forbidden = [str(value) for value in template.get("forbidden_copy_terms", []) if str(value).strip()]
    with Image.open(candidate) as image:
        width, height = image.size
    with Image.open(blueprint_path) as image:
        bw, bh = image.size
    candidate_ratio = width / max(height, 1)
    ratio_targets: list[tuple[str, float]] = [("blueprint", bw / max(bh, 1))]
    for value in acceptable_aspect_ratios or []:
        try:
            left, right = str(value).split(":", 1)
            parsed = float(left) / float(right)
        except Exception:
            continue
        if parsed <= 0 or any(abs(parsed - target) <= 0.001 for _, target in ratio_targets):
            continue
        ratio_targets.append((str(value), parsed))
    ratio_errors = {
        label: round(abs(candidate_ratio - target) / max(target, 0.01), 5)
        for label, target in ratio_targets
    }
    matched_ratio, ratio_error = min(ratio_errors.items(), key=lambda item: item[1])
    basic = {
        "summary": "Deterministic candidate checks.",
        "valid_image": width > 0 and height > 0,
        "width": width,
        "height": height,
        "blueprint_width": bw,
        "blueprint_height": bh,
        "candidate_aspect_ratio": round(candidate_ratio, 5),
        "acceptable_aspect_ratios": [label for label, _ in ratio_targets],
        "aspect_ratio_errors": ratio_errors,
        "matched_aspect_ratio": matched_ratio,
        "aspect_ratio_error": ratio_error,
        "passed": ratio_error <= 0.08 and min(width, height) >= 512,
    }

    local_records: list[dict] = []
    local_engine = "not_run"
    local_warning = None
    requested_engine = ocr_engine
    if requested_engine == "auto":
        requested_engine = "paddle"
    if requested_engine in {"paddle", "easyocr"}:
        local_records, local_engine, local_warning = _local_ocr(candidate, requested_engine, ocr_lang, adapter=ocr_adapter)

    topology_name = str(plan.get("figure_specification", {}).get("topology") or "unknown")
    topology_required = topology_name in {"feedback", "branch", "multimodal", "dense_multiframe"} or str(template.get("template_id") or "") in {"feedback", "arbor"}
    vlm_raw: dict = {}
    topology_raw: dict = {}
    vlm_warning = None
    topology_warning = None
    review_available = vlm_credentials_available() or critic_adapter or topology_adapter
    if mode == "vlm" and review_available:
        with ThreadPoolExecutor(max_workers=2 if topology_required else 1) as executor:
            critic_future = executor.submit(
                _vlm_critic,
                candidate,
                blueprint_path,
                plan,
                template,
                labels,
                repeatable_labels,
                forbidden,
                model,
                critic_adapter,
            )
            topology_future = executor.submit(_vlm_topology_critic, candidate, plan, model, topology_adapter) if topology_required else None
            try:
                vlm_raw = critic_future.result()
            except Exception as exc:
                vlm_warning = str(exc)
            if topology_future is not None:
                try:
                    topology_raw = topology_future.result()
                except Exception as exc:
                    topology_warning = str(exc)
    elif mode == "vlm":
        vlm_warning = "VLM review credentials unavailable"
        if topology_required:
            topology_warning = vlm_warning

    detected_local = [str(item.get("text") or "").strip() for item in local_records if str(item.get("text") or "").strip()]
    ocr = _normalize_section(vlm_raw.get("ocr"), "OCR")
    if detected_local:
        joined = _normalize_text(" ".join(detected_local))
        missing = [label for label in labels if _normalize_text(label) not in joined]
        forbidden_found = [label for label in forbidden if _normalize_text(label) and _normalize_text(label) in joined]
        ocr.update({
            "local_engine": local_engine,
            "local_detected_text": detected_local,
            "missing_labels": missing,
            "forbidden_labels_found": forbidden_found,
            "score": round((len(labels) - len(missing)) / max(len(labels), 1), 4),
            "passed": not missing and not forbidden_found,
        })
    else:
        ocr.setdefault("local_engine", local_engine)
        ocr.setdefault("local_detected_text", [])
    repeatable_normalized = {_normalize_text(value) for value in repeatable_labels if _normalize_text(value)}
    duplicate_labels = [str(value) for value in ocr.get("duplicate_labels", [])]
    allowed_duplicate_labels = [value for value in duplicate_labels if _normalize_text(value) in repeatable_normalized]
    ocr["allowed_duplicate_labels"] = allowed_duplicate_labels
    ocr["duplicate_labels"] = [value for value in duplicate_labels if _normalize_text(value) not in repeatable_normalized]
    scientific = _normalize_section(vlm_raw.get("scientific"), "Scientific")
    template_review = _normalize_section(vlm_raw.get("template"), "Template")
    aesthetic = _normalize_section(vlm_raw.get("aesthetic"), "Aesthetic")
    topology_review = _normalize_section(topology_raw, "Topology") if topology_required else {"summary": "Focused topology review not required for this topology.", "score": 1.0, "passed": True, "skipped": True}
    topology_issues = sum(len(topology_review.get(field, [])) for field in ["missing_relations", "reversed_relations", "bypassed_relations", "invented_relations"])
    if topology_required:
        topology_review["passed"] = bool(topology_review.get("passed")) and topology_review["score"] >= 0.9 and topology_issues == 0 and not topology_warning
    ocr_issues = sum(len(ocr.get(field, [])) for field in ["missing_labels", "misspelled_labels", "duplicate_labels", "forbidden_labels_found"])
    if ocr_issues == 0:
        ocr["score"] = 1.0
    ocr["passed"] = ocr["score"] >= 0.999 and ocr_issues == 0
    scientific_issues = sum(len(scientific.get(field, [])) for field in ["missing_modules", "missing_relations", "reversed_relations", "invented_items"])
    has_innovations = bool(plan.get("figure_specification", {}).get("innovations"))
    innovation_ok = not has_innovations or bool(scientific.get("innovation_visible", False))
    if scientific_issues == 0 and innovation_ok:
        scientific["score"] = 1.0
    scientific["passed"] = scientific["score"] >= 0.95 and scientific_issues == 0 and innovation_ok
    copied = template_review.get("copied_reference_content", [])
    template_review["passed"] = template_review["score"] >= 0.70 and not copied
    aesthetic["passed"] = aesthetic["score"] >= 0.70
    if mode != "vlm":
        template_review.update({"score": 1.0 if basic["passed"] else 0.0, "passed": basic["passed"], "engineering_only": True})
        aesthetic.update({"score": 0.0, "passed": False, "engineering_only": True})
        scientific.update({"score": 0.0, "passed": False, "engineering_only": True})
        ocr.update({"score": 0.0, "passed": False, "engineering_only": True})
    hard_errors = []
    for value in vlm_raw.get("hard_errors", []):
        text = str(value)
        normalized_error = _normalize_text(text)
        allowed_duplicate_error = "duplicate" in text.casefold() and any(label in normalized_error for label in repeatable_normalized)
        contradicted_template_error = "template" in text.casefold() and template_review["passed"] and template_review["score"] >= 0.70
        if not allowed_duplicate_error and not contradicted_template_error:
            hard_errors.append(text)
    if topology_required and not topology_review["passed"]:
        hard_errors.extend(_issue_text(value) for value in topology_review.get("missing_relations", []))
        hard_errors.extend(_issue_text(value) for value in topology_review.get("reversed_relations", []))
        hard_errors.extend(_issue_text(value) for value in topology_review.get("bypassed_relations", []))
        hard_errors.extend(_issue_text(value) for value in topology_review.get("invented_relations", []))
        if topology_warning:
            hard_errors.append(f"Focused topology review unavailable: {topology_warning}")
    hard_errors = list(dict.fromkeys(value for value in hard_errors if value))
    repair = list(vlm_raw.get("repair", []))
    repair.extend(_issue_text(value) for value in topology_review.get("repair", []) if _issue_text(value))
    repair_regions = list(vlm_raw.get("repair_regions", []))
    repair_regions.extend(_issue_text(value) for value in topology_review.get("repair_regions", []) if _issue_text(value))
    production_pass = bool(basic["passed"] and ocr["passed"] and scientific["passed"] and topology_review["passed"] and template_review["passed"] and aesthetic["passed"] and not hard_errors)
    score = 0.25 * scientific["score"] + 0.20 * ocr["score"] + 0.20 * topology_review["score"] + 0.20 * template_review["score"] + 0.15 * aesthetic["score"]
    return {
        "summary": "Four-layer production candidate review.",
        "path": str(candidate),
        "mode": mode,
        "basic": basic,
        "ocr": ocr,
        "scientific": scientific,
        "topology": topology_review,
        "template": template_review,
        "aesthetic": aesthetic,
        "hard_errors": hard_errors,
        "preserve": list(vlm_raw.get("preserve", [])),
        "repair": list(dict.fromkeys(repair)),
        "remove": list(vlm_raw.get("remove", [])),
        "repair_regions": list(dict.fromkeys(repair_regions)),
        "local_ocr_warning": local_warning,
        "vlm_warning": vlm_warning,
        "topology_warning": topology_warning,
        "production_pass": production_pass,
        "overall_score": round(score, 4),
    }


def aggregate_reviews(records: list[dict]) -> dict:
    def collect(section: str) -> dict:
        return {"summary": f"Aggregated {section} candidate reviews.", "candidates": [{"candidate_id": item["candidate_id"], **item["review"][section]} for item in records]}
    return {
        "ocr_review": collect("ocr"),
        "scientific_critic_report": collect("scientific"),
        "topology_critic_report": collect("topology"),
        "template_alignment_report": collect("template"),
        "aesthetic_critic_report": collect("aesthetic"),
    }
