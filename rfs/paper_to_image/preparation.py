from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from ..utils import ensure_dir, read_json, write_json, write_text
from .analyzer import paper_markdown, parse_paper
from .contract_completion import augment_contract_from_evidence
from .document_cache import DOCUMENT_CACHE_VERSION, read_document_cache, write_document_cache
from .planner import build_review_grounded_plan, compile_image_prompt, merge_preferences, plan_fast_paper_contract, plan_paper_image, validate_plan_grounding
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


def _review_evidence_map(value: Any) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    if isinstance(value, dict):
        item_id = str(value.get("id") or "").strip()
        evidence_ids = [str(item) for item in value.get("evidence_ids", []) if str(item).startswith("E")]
        if item_id and evidence_ids:
            mapping[item_id] = evidence_ids
        for child in value.values():
            mapping.update(_review_evidence_map(child))
    elif isinstance(value, list):
        for child in value:
            mapping.update(_review_evidence_map(child))
    return mapping


def expand_plan_evidence(plan: dict[str, Any], paper_review: dict[str, Any], parsed: dict[str, Any]) -> None:
    mapping = _review_evidence_map(paper_review)
    valid = {item["id"] for item in parsed.get("evidence", [])}
    legacy = {item.get("legacy_id"): item["id"] for item in parsed.get("evidence", []) if item.get("legacy_id")}
    def expand(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("evidence_ids"), list):
                expanded = []
                for item in value["evidence_ids"]:
                    key = str(item)
                    if key in valid:
                        expanded.append(key)
                    elif key in legacy:
                        expanded.append(legacy[key])
                    else:
                        expanded.extend(mapping.get(key, []))
                value["evidence_ids"] = list(dict.fromkeys(expanded))
            for child in value.values():
                expand(child)
        elif isinstance(value, list):
            for child in value:
                expand(child)
    expand(plan)


def _item_id(item: dict[str, Any], field: str, index: int) -> str:
    return str(item.get("id") or item.get("name") or item.get("visible_label") or item.get("text") or item.get("statement") or f"{field}_{index}").strip()


def _item_label(item: dict[str, Any]) -> str:
    return str(item.get("visible_label") or item.get("name") or item.get("text") or item.get("statement") or item.get("label") or item.get("id") or "").strip()


def _normalized_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _script_counts(value: str) -> tuple[int, int]:
    cjk = sum(
        "\u3400" <= char <= "\u9fff"
        or "\u3040" <= char <= "\u30ff"
        or "\uac00" <= char <= "\ud7af"
        for char in str(value or "")
    )
    latin = sum(("a" <= char.casefold() <= "z") for char in str(value or ""))
    return cjk, latin


def _repair_cross_script_terminology(spec: dict[str, Any], parsed: dict[str, Any]) -> None:
    terminology = spec.get("terminology") if isinstance(spec.get("terminology"), dict) else {}
    if not terminology:
        return
    corpus = " ".join(str(item.get("text") or "") for item in parsed.get("evidence", []) if isinstance(item, dict))
    normalized_corpus = re.sub(r"\s+", " ", corpus.casefold())
    repaired: dict[str, str] = {}
    for source_term, visible_label in terminology.items():
        source = str(source_term or "").strip()
        visible = str(visible_label or "").strip()
        source_present = bool(source and re.sub(r"\s+", " ", source.casefold()) in normalized_corpus)
        visible_present = bool(visible and re.sub(r"\s+", " ", visible.casefold()) in normalized_corpus)
        source_cjk, source_latin = _script_counts(source)
        visible_cjk, visible_latin = _script_counts(visible)
        changed_script = (source_cjk >= 2 and visible_cjk == 0 and visible_latin >= 2) or (source_latin >= 4 and source_cjk == 0 and visible_cjk >= 2 and visible_latin == 0)
        repaired[source] = source if source_present and not visible_present and changed_script else visible
    spec["terminology"] = repaired


def _ground_exact_visible_entities(spec: dict[str, Any], parsed: dict[str, Any]) -> list[str]:
    evidence = [item for item in parsed.get("evidence", []) if isinstance(item, dict) and item.get("id") and item.get("text")]
    novelty_pattern = re.compile(r"\b(?:we\s+(?:introduce|propose|present|develop)|novel|new\s+(?:method|model|system|framework)|contribution)\b|\u672c\u6587\u63d0\u51fa|\u6211\u4eec\u63d0\u51fa|\u9996\u6b21|\u521b\u65b0", re.IGNORECASE)
    overview_pattern = re.compile(r"overview|framework|architecture|pipeline|procedure|pre-training|fine-tuning|system|model|\u6846\u67b6|\u67b6\u6784|\u7cfb\u7edf", re.IGNORECASE)
    overview_pages = {
        int(item.get("page") or 0)
        for item in parsed.get("document_index", {}).get("figures", [])
        if isinstance(item, dict) and overview_pattern.search(str(item.get("caption") or ""))
    }
    grounded: list[str] = []
    for field in ("inputs", "modules", "outputs", "innovations"):
        for index, item in enumerate(spec.get(field, []) if isinstance(spec.get(field), list) else []):
            if not isinstance(item, dict) or item.get("evidence_ids"):
                continue
            label = _item_label(item)
            compact = _normalized_label(label)
            if not compact:
                continue
            matches = []
            for record in evidence:
                record_compact = _normalized_label(str(record.get("text") or ""))
                short_diagram_label = len(compact) < 3 and int(record.get("page") or 0) in overview_pages and record_compact == compact
                if not short_diagram_label and (len(compact) < 3 or compact not in record_compact):
                    continue
                if field == "innovations" and not novelty_pattern.search(str(record.get("text") or "")):
                    continue
                matches.append(str(record["id"]))
            if not matches:
                continue
            item["evidence_ids"] = list(dict.fromkeys(matches))[:3]
            grounded.append(f"{field}[{index}]")
    return grounded


def _stable_id(prefix: str, value: str, index: int) -> str:
    slug = "_".join(part for part in re.sub(r"[^a-z0-9]+", " ", value.casefold()).split() if part)[:48]
    return f"{prefix}_{slug or index}"


def _statement_object(value: Any, fallback: Any = None) -> dict[str, Any]:
    candidate = value if value is not None else fallback
    if isinstance(candidate, dict):
        item = dict(candidate)
        text = str(item.get("text") or item.get("statement") or "unknown").strip() or "unknown"
        item["text"] = text
        item["evidence_ids"] = list(item.get("evidence_ids")) if isinstance(item.get("evidence_ids"), list) else []
        return item
    if isinstance(candidate, str) and candidate.strip():
        return {"text": candidate.strip(), "evidence_ids": []}
    return {"text": "unknown", "evidence_ids": [], "status": "unknown"}


def _infer_topology(spec: dict[str, Any]) -> str:
    relations = [item for item in spec.get("relations", []) if isinstance(item, dict)]
    if any("feedback" in str(item.get("type") or "").casefold() for item in relations):
        return "feedback"
    inputs = [item for item in spec.get("inputs", []) if isinstance(item, dict)]
    labels = " ".join(_item_label(item).casefold() for item in inputs)
    modalities = sum(term in labels for term in ("image", "text", "audio", "video", "depth", "thermal", "imu"))
    modules = [item for item in spec.get("modules", []) if isinstance(item, dict)]
    encoder_count = sum("encoder" in _item_label(item).casefold() for item in modules)
    if modalities >= 3 or (modalities >= 2 and encoder_count >= 2):
        return "multimodal"
    outgoing: dict[str, int] = {}
    for relation in relations:
        source = str(relation.get("source") or relation.get("source_id") or "")
        outgoing[source] = outgoing.get(source, 0) + 1
    if any(value > 1 for value in outgoing.values()):
        return "branch"
    overview_panels = [item for item in spec.get("modules", []) if isinstance(item, dict) and str(item.get("role") or "") == "overview_panel"]
    if len(overview_panels) >= 3:
        return "dense_multiframe"
    return "linear" if relations else "unknown"


def _complete_from_overview_caption(spec: dict[str, Any], parsed: dict[str, Any]) -> None:
    figures = parsed.get("document_index", {}).get("figures", [])
    figure = next((item for item in figures if re.match(r"^(figure|fig\.)\s*1\b", str(item.get("caption") or ""), re.IGNORECASE) and re.search(r"\b(components?|overview|framework|architecture|pipeline)\b", str(item.get("caption") or ""), re.IGNORECASE)), None)
    figure = figure or next((item for item in figures if re.search(r"\b(overview|framework|architecture|pipeline)\b", str(item.get("caption") or ""), re.IGNORECASE)), None)
    figure = figure or next((item for item in figures if re.match(r"^(figure|fig\.)\s*1\b", str(item.get("caption") or ""), re.IGNORECASE)), None)
    if not figure:
        return
    caption = str(figure.get("caption") or "")
    caption_evidence = next((item["id"] for item in parsed.get("evidence", []) if item.get("kind") == "caption" and item.get("page") == figure.get("page") and str(item.get("text") or "").startswith(str(caption)[:60])), None)
    evidence_ids = [caption_evidence] if caption_evidence else []
    match = re.search(r"(?:interconnected\s+)?components\s*:\s*(.+)", caption, re.IGNORECASE)
    component_ids: dict[str, str] = {}
    if match:
        raw_components = re.split(r",\s+(?=(?:and\s+)?(?:a|an)\s+)", match.group(1))
        existing = {_normalized_label(_item_label(item)) for field in ("modules", "inputs", "outputs", "innovations") for item in (spec.get(field, []) if isinstance(spec.get(field), list) else []) if isinstance(item, dict)}
        for index, raw in enumerate(raw_components):
            phrase = re.sub(r"^(?:and\s+)?(?:a|an)\s+", "", raw.strip(), flags=re.IGNORECASE)
            phrase = re.split(r"\s+(?:that|which|for|by|to)\s+", phrase, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .")
            if not 3 <= len(phrase) <= 80:
                continue
            label = phrase[0].upper() + phrase[1:]
            normalized = _normalized_label(label)
            existing_match = next((item for item in spec.get("modules", []) if isinstance(item, dict) and normalized and (normalized in _normalized_label(_item_label(item)) or _normalized_label(_item_label(item)) in normalized)), None)
            if existing_match:
                component_ids[normalized] = str(existing_match.get("id"))
                continue
            if normalized not in existing:
                item_id = _stable_id("overview", label, index)
                spec.setdefault("modules", []).append({"id": item_id, "name": label, "role": "overview_panel", "evidence_ids": evidence_ids})
                existing.add(normalized)
                component_ids[normalized] = item_id
    dataset_match = re.search(r"\b([A-Z]{2,}[A-Z0-9-]*\d[A-Z0-9-]*)\b", caption) if re.search(r"\bdataset\b|data engine|collecting", caption, re.IGNORECASE) else None
    dataset_item = None
    if dataset_match:
        dataset_label = dataset_match.group(1)
        dataset_item = next((item for item in spec.get("outputs", []) if isinstance(item, dict) and dataset_label.casefold() in _item_label(item).casefold()), None)
        if not dataset_item:
            dataset_item = {"id": _stable_id("dataset", dataset_label, 0), "name": dataset_label, "role": "dataset", "evidence_ids": evidence_ids}
            spec.setdefault("outputs", []).append(dataset_item)
    model_item = next((item for item in spec.get("modules", []) if isinstance(item, dict) and ("segmentation model" in _item_label(item).casefold() or "segment anything model" in _item_label(item).casefold())), None)
    model_item = model_item or next((item for item in spec.get("modules", []) if isinstance(item, dict) and ("model" in _item_label(item).casefold() or "sam" in _item_label(item).casefold())), None)
    engine_item = next((item for item in spec.get("modules", []) if isinstance(item, dict) and "data engine" in _item_label(item).casefold()), None)
    relations = spec.setdefault("relations", [])
    pairs = {(str(item.get("source")), str(item.get("target"))) for item in relations if isinstance(item, dict)}
    if model_item and engine_item and (str(model_item.get("id")), str(engine_item.get("id"))) not in pairs and re.search(r"powers?\s+data\s+annotation|data\s+engine", caption, re.IGNORECASE):
        relations.append({"source": str(model_item.get("id")), "target": str(engine_item.get("id")), "type": "annotation_support", "label": "", "evidence_ids": evidence_ids})
        pairs.add((str(model_item.get("id")), str(engine_item.get("id"))))
    evidence = parsed.get("evidence", [])
    for index, item in enumerate(evidence):
        if not re.search(r"has\s+(?:three|3)\s+stages", str(item.get("text") or ""), re.IGNORECASE):
            continue
        combined = " ".join(str(value.get("text") or "") for value in evidence[index:index + 3])
        stage_match = re.search(r"([A-Za-z]+(?:-[A-Za-z]+)?)\s*,\s*([A-Za-z]+(?:-[A-Za-z]+)?)\s*,\s*(?:and\s+)?([A-Za-z]+(?:\s+[A-Za-z]+)?)\s*\.", combined)
        if not stage_match:
            continue
        stage_evidence = [value["id"] for value in evidence[index:index + 3]]
        stage_items = []
        for stage_index, value in enumerate(stage_match.groups()):
            label = value.strip().title().replace("-", "-")
            existing_stage = next((module for module in spec.get("modules", []) if isinstance(module, dict) and _normalized_label(label) == _normalized_label(_item_label(module))), None)
            if existing_stage:
                stage_items.append(existing_stage)
            else:
                stage = {"id": _stable_id("stage", label, stage_index), "name": label, "role": "data_engine_stage", "evidence_ids": stage_evidence}
                spec.setdefault("modules", []).append(stage)
                stage_items.append(stage)
        for source, target in zip(stage_items, stage_items[1:]):
            pair = (str(source.get("id")), str(target.get("id")))
            if pair not in pairs:
                relations.append({"source": pair[0], "target": pair[1], "type": "stage_transition", "label": "", "evidence_ids": stage_evidence})
                pairs.add(pair)
        if dataset_item and stage_items:
            pair = (str(stage_items[-1].get("id")), str(dataset_item.get("id")))
            if pair not in pairs:
                relations.append({"source": pair[0], "target": pair[1], "type": "data_generation", "label": "", "evidence_ids": stage_evidence + evidence_ids})
        break


def _normalize_contract_entities(raw_items: Any, field: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items if isinstance(raw_items, list) else []):
        if isinstance(raw, str) and raw.strip():
            item = {"name": raw.strip(), "evidence_ids": []}
        elif isinstance(raw, dict):
            item = dict(raw)
        else:
            continue
        label = _item_label(item)
        if not label:
            continue
        item["id"] = str(item.get("id") or _stable_id(field.rstrip("s"), label, index)).strip()
        item["evidence_ids"] = list(item.get("evidence_ids")) if isinstance(item.get("evidence_ids"), list) else []
        normalized.append(item)
    return normalized


def _normalize_contract_relations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    aliases: dict[str, set[str]] = {}
    endpoint_ids: set[str] = set()
    for field in ("inputs", "modules", "outputs", "innovations"):
        for item in spec.get(field, []) if isinstance(spec.get(field), list) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            item_id = str(item["id"])
            endpoint_ids.add(item_id)
            for value in (item_id, _item_label(item)):
                normalized = _normalized_label(str(value))
                if normalized:
                    aliases.setdefault(normalized, set()).add(item_id)

    def resolve(value: Any) -> str:
        raw = str(value or "").strip()
        if raw in endpoint_ids:
            return raw
        matches = aliases.get(_normalized_label(raw), set())
        return next(iter(matches)) if len(matches) == 1 else raw

    normalized_relations: list[dict[str, Any]] = []
    for raw in spec.get("relations", []) if isinstance(spec.get("relations"), list) else []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        source = resolve(item.get("source") or item.get("source_id"))
        target = resolve(item.get("target") or item.get("target_id"))
        if not source or not target:
            continue
        item["source"] = source
        item["target"] = target
        item["type"] = str(item.get("type") or item.get("relation_type") or "data_flow")
        item["label"] = str(item.get("label") or "")
        item["evidence_ids"] = list(item.get("evidence_ids")) if isinstance(item.get("evidence_ids"), list) else []
        normalized_relations.append(item)
    return normalized_relations


def _repair_contract_relation_endpoints(spec: dict[str, Any]) -> dict[str, list[str]]:
    endpoints = {
        str(item.get("id")): item
        for field in ("inputs", "modules", "outputs", "innovations")
        for item in (spec.get(field, []) if isinstance(spec.get(field), list) else [])
        if isinstance(item, dict) and item.get("id")
    }
    label_matches: dict[str, set[str]] = {}
    for item_id, item in endpoints.items():
        normalized = _normalized_label(_item_label(item))
        if normalized:
            label_matches.setdefault(normalized, set()).add(item_id)

    replacements: dict[str, str] = {}
    repaired: list[str] = []
    relations = [item for item in spec.get("relations", []) if isinstance(item, dict)]
    for relation in relations:
        target = str(relation.get("target") or "")
        if target in endpoints:
            continue
        label = _normalized_label(str(relation.get("label") or ""))
        matches = label_matches.get(label, set())
        if target and label and len(matches) == 1:
            replacement = next(iter(matches))
            replacements[target] = replacement
            relation["target"] = replacement
            repaired.append(f"{target}->{replacement}")

    for relation in relations:
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        if source in replacements:
            relation["source"] = replacements[source]
        if target in replacements:
            relation["target"] = replacements[target]

    deduplicated: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    removed_duplicates: list[str] = []
    removed_unresolved: list[str] = []
    for relation in relations:
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        relation_type = str(relation.get("type") or "data_flow")
        if source not in endpoints or target not in endpoints:
            removed_unresolved.append(f"{source}->{target}")
            continue
        key = (source, target, relation_type)
        existing = by_key.get(key)
        if existing:
            existing["evidence_ids"] = list(dict.fromkeys(list(existing.get("evidence_ids", [])) + list(relation.get("evidence_ids", []))))
            if not existing.get("label") and relation.get("label"):
                existing["label"] = relation["label"]
            removed_duplicates.append(f"{source}->{target}:{relation_type}")
            continue
        by_key[key] = relation
        deduplicated.append(relation)
    spec["relations"] = deduplicated
    return {
        "repaired": list(dict.fromkeys(repaired)),
        "removed_duplicates": list(dict.fromkeys(removed_duplicates)),
        "removed_unresolved": list(dict.fromkeys(removed_unresolved)),
    }

def normalize_figure_contract(plan: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("paper_summary") if isinstance(plan.get("paper_summary"), dict) else {}
    spec = plan.get("figure_specification") if isinstance(plan.get("figure_specification"), dict) else {}
    spec["research_problem"] = _statement_object(spec.get("research_problem"), summary.get("research_problem"))
    spec["central_claim"] = _statement_object(spec.get("central_claim"), summary.get("central_claim"))
    if not isinstance(spec.get("inputs"), list) or not spec.get("inputs"):
        spec["inputs"] = summary.get("inputs") if isinstance(summary.get("inputs"), list) else []
    if not isinstance(spec.get("outputs"), list) or not spec.get("outputs"):
        spec["outputs"] = summary.get("outputs") if isinstance(summary.get("outputs"), list) else []
    if not isinstance(spec.get("modules"), list) or not spec.get("modules"):
        summary_modules = summary.get("core_modules") if isinstance(summary.get("core_modules"), list) else summary.get("modules")
        spec["modules"] = summary_modules if isinstance(summary_modules, list) else []
    for field in ("inputs", "modules", "outputs", "innovations"):
        spec[field] = _normalize_contract_entities(spec.get(field), field)
    spec["relations"] = _normalize_contract_relations(spec)
    completion_report = augment_contract_from_evidence(spec, parsed)
    plan["contract_completion_report"] = completion_report
    if len(completion_report.get("added_entities", [])) >= 3:
        fallback_ids = {
            str(item.get("id"))
            for item in (spec.get("modules", []) if isinstance(spec.get("modules"), list) else [])
            if isinstance(item, dict) and str(item.get("role") or "") == "paper-derived stage requiring VLM verification"
        }
        if fallback_ids:
            spec["modules"] = [item for item in spec.get("modules", []) if not (isinstance(item, dict) and str(item.get("id")) in fallback_ids)]
            spec["relations"] = [
                item for item in spec.get("relations", []) if not (
                    isinstance(item, dict)
                    and (str(item.get("source")) in fallback_ids or str(item.get("target")) in fallback_ids)
                )
            ]
            completion_report["removed_fallback_entities"] = sorted(fallback_ids)
    _complete_from_overview_caption(spec, parsed)
    endpoint_report = _repair_contract_relation_endpoints(spec)
    completion_report["relation_endpoint_repairs"] = endpoint_report["repaired"]
    completion_report["removed_duplicate_relations"] = endpoint_report["removed_duplicates"]
    completion_report["removed_unresolved_relations"] = endpoint_report["removed_unresolved"]
    if endpoint_report["repaired"]:
        secondary_completion = augment_contract_from_evidence(spec, parsed)
        for key in ("added_entities", "upgraded_entities", "adopted_entities", "added_relations", "repaired_relations", "grounded_entities"):
            completion_report[key] = list(dict.fromkeys(list(completion_report.get(key, [])) + list(secondary_completion.get(key, []))))
    modules = spec.get("modules") if isinstance(spec.get("modules"), list) else []
    encoder_modules = [item for item in modules if isinstance(item, dict) and "encoder" in _item_label(item).casefold() and "modality encoder" not in _item_label(item).casefold()]
    if len(encoder_modules) >= 3:
        group_id = "modality_encoders_group"
        evidence_ids = list(dict.fromkeys(value for item in encoder_modules for value in item.get("evidence_ids", [])))
        if not any(str(item.get("id")) == group_id for item in modules if isinstance(item, dict)):
            modules.append({"id": group_id, "name": "Modality Encoders", "role": "group", "evidence_ids": evidence_ids})
        relations = spec.get("relations") if isinstance(spec.get("relations"), list) else []
        encoder_ids = {str(item.get("id")) for item in encoder_modules}
        endpoints = modules + list(spec.get("outputs", []) if isinstance(spec.get("outputs"), list) else []) + list(spec.get("innovations", []) if isinstance(spec.get("innovations"), list) else [])
        joint_items = [item for item in endpoints if isinstance(item, dict) and "joint" in _item_label(item).casefold() and ("embedding" in _item_label(item).casefold() or "representation" in _item_label(item).casefold())]
        existing = {(str(item.get("source")), str(item.get("target"))) for item in relations if isinstance(item, dict)}
        for relation in list(relations):
            if not isinstance(relation, dict) or str(relation.get("target")) not in encoder_ids:
                continue
            pair = (str(relation.get("source")), group_id)
            if pair not in existing:
                relations.append({"source": pair[0], "target": pair[1], "type": "encoding", "label": "", "evidence_ids": list(relation.get("evidence_ids", []))})
                existing.add(pair)
        modality_terms = ("image", "text", "audio", "depth", "thermal", "imu", "video", "modalit")
        for item in spec.get("inputs", []) if isinstance(spec.get("inputs"), list) else []:
            if not isinstance(item, dict) or not any(term in _item_label(item).casefold() for term in modality_terms):
                continue
            pair = (str(item.get("id")), group_id)
            if pair not in existing:
                relations.append({"source": pair[0], "target": pair[1], "type": "encoding", "label": "", "evidence_ids": list(item.get("evidence_ids", []))})
                existing.add(pair)
        for joint in joint_items:
            if any(str(item.get("source")) in encoder_ids and str(item.get("target")) == str(joint.get("id")) for item in relations if isinstance(item, dict)):
                pair = (group_id, str(joint.get("id")))
                if pair not in existing:
                    relations.append({"source": pair[0], "target": pair[1], "type": "alignment", "label": "", "evidence_ids": evidence_ids})
                    existing.add(pair)
        emergent_items = [
            item for item in endpoints
            if isinstance(item, dict)
            and (("emergent" in _item_label(item).casefold() and "align" in _item_label(item).casefold()) or "binding" in _item_label(item).casefold())
        ]
        if not emergent_items:
            emergent_relation = next((item for item in relations if isinstance(item, dict) and "emergent" in str(item.get("label") or "").casefold() and "align" in str(item.get("label") or "").casefold()), None)
            if emergent_relation:
                emergent = {"id": "emergent_alignment_concept", "statement": "Emergent Alignment", "role": "innovation", "evidence_ids": list(emergent_relation.get("evidence_ids", []))}
                spec.setdefault("innovations", []).append(emergent)
                emergent_items.append(emergent)
        for joint in joint_items:
            for emergent in emergent_items:
                pair = (str(joint.get("id")), str(emergent.get("id")))
                if pair not in existing:
                    relations.append({"source": pair[0], "target": pair[1], "type": "enables", "label": "emergent alignment", "evidence_ids": list(emergent.get("evidence_ids", []))})
                    existing.add(pair)
        spec["relations"] = relations
        spec["modules"] = modules
    modules = spec.get("modules") if isinstance(spec.get("modules"), list) else []
    relations = spec.get("relations") if isinstance(spec.get("relations"), list) else []
    existing_labels = [_normalized_label(_item_label(item)) for field in ("inputs", "modules", "outputs", "innovations") for item in (spec.get(field, []) if isinstance(spec.get(field), list) else []) if isinstance(item, dict)]
    component_terms = ("token", "embedding", "encoder", "decoder", "head", "branch", "prompt", "proposal", "mask", "engine", "dataset")
    for index, item in enumerate(spec.get("must_show", []) if isinstance(spec.get("must_show"), list) else []):
        if not isinstance(item, dict):
            continue
        text = _item_label(item)
        normalized = _normalized_label(text)
        if not text or len(text) > 80 or not any(term in text.casefold() for term in component_terms):
            continue
        if any(normalized and (normalized in label or label in normalized) for label in existing_labels if label):
            continue
        module = {"id": _stable_id("required", text, index), "name": text, "role": "required_component", "evidence_ids": list(item.get("evidence_ids", []))}
        modules.append(module)
        existing_labels.append(normalized)
    spec["modules"] = modules
    existing_pairs = {(str(item.get("source")), str(item.get("target"))) for item in relations if isinstance(item, dict)}
    transformer_target = next((item for item in modules if "transformer encoder" in _item_label(item).casefold()), None)
    for item in modules:
        label = _item_label(item).casefold()
        normalized_component = _normalized_label(label)
        if transformer_target and str(item.get("id")) != str(transformer_target.get("id")) and any(term in normalized_component for term in ("classtoken", "classificationtoken", "positionembedding")):
            pair = (str(item.get("id")), str(transformer_target.get("id")))
            if pair not in existing_pairs:
                relations.append({"source": pair[0], "target": pair[1], "type": "conditioning", "label": "", "evidence_ids": list(item.get("evidence_ids", []))})
                existing_pairs.add(pair)
    outgoing = {str(item.get("source")) for item in relations if isinstance(item, dict)}
    incoming = {str(item.get("target")) for item in relations if isinstance(item, dict)}
    def choose_input_target(label: str) -> dict[str, Any] | None:
        preferences = []
        low = label.casefold()
        if any(term in low for term in ("prompt", "提示", "プロンプト", "프롬프트")):
            preferences = ["prompt encoder", "提示编码器", "提示編碼器", "プロンプトエンコーダ", "프롬프트 인코더", "encoder", "decoder"]
        elif any(term in low for term in ("image", "video", "图像", "圖像", "影像", "视频", "影片", "画像", "動画", "이미지", "영상")):
            preferences = ["patch", "image encoder", "图像编码器", "圖像編碼器", "画像エンコーダ", "이미지 인코더", "backbone", "encoder"]
        elif any(term in low for term in ("text", "文本", "文字", "テキスト", "텍스트")):
            preferences = ["text encoder", "文本编码器", "文本編碼器", "テキストエンコーダ", "텍스트 인코더", "modality encoders", "encoder"]
        elif any(term in low for term in ("audio", "音频", "音訊", "音声", "오디오")):
            preferences = ["audio encoder", "音频编码器", "音訊編碼器", "音声エンコーダ", "오디오 인코더", "modality encoders", "encoder"]
        elif any(term in low for term in ("depth", "thermal", "imu", "深度", "热成像", "熱成像")):
            preferences = ["modality encoders", "encoder", "编码器", "編碼器", "エンコーダ", "인코더"]
        for preference in preferences:
            match = next((module for module in modules if preference and preference in _item_label(module).casefold()), None)
            if match:
                return match
        return None
    for item in spec.get("inputs", []) if isinstance(spec.get("inputs"), list) else []:
        source = str(item.get("id"))
        if not source or source in outgoing:
            continue
        target = choose_input_target(_item_label(item))
        if target:
            pair = (source, str(target.get("id")))
            if pair not in existing_pairs:
                relations.append({"source": pair[0], "target": pair[1], "type": "data_flow", "label": "", "evidence_ids": list(dict.fromkeys(list(item.get("evidence_ids", [])) + list(target.get("evidence_ids", []))))})
                existing_pairs.add(pair)
                outgoing.add(source)
                incoming.add(pair[1])
    module_sources = {str(item.get("source")) for item in relations if isinstance(item, dict)}
    sink_modules = [item for item in modules if str(item.get("id")) not in module_sources]
    for item in spec.get("outputs", []) if isinstance(spec.get("outputs"), list) else []:
        target_id = str(item.get("id"))
        if not target_id or target_id in incoming:
            continue
        output_label = _item_label(item).casefold()
        source = next((module for module in reversed(modules) if any(term in _item_label(module).casefold() for term in ("head", "decoder", "refine", "classifier", "predict"))), None)
        if "mask" in output_label:
            source = next((module for module in modules if "mask decoder" in _item_label(module).casefold() or "mask branch" in _item_label(module).casefold()), source)
        elif "box" in output_label or "bounding" in output_label or "class" in output_label or "category" in output_label:
            source = next((module for module in modules if "box branch" in _item_label(module).casefold() or "classification head" in _item_label(module).casefold()), source)
        source = source or (sink_modules[-1] if sink_modules else modules[-1] if modules else None)
        if source:
            pair = (str(source.get("id")), target_id)
            if pair not in existing_pairs:
                relations.append({"source": pair[0], "target": pair[1], "type": "data_flow", "label": "", "evidence_ids": list(dict.fromkeys(list(source.get("evidence_ids", [])) + list(item.get("evidence_ids", []))))})
                existing_pairs.add(pair)
                incoming.add(target_id)
    spec["relations"] = relations
    spec.setdefault("training_flow", summary.get("training_flow") if isinstance(summary.get("training_flow"), list) else [])
    spec.setdefault("inference_flow", summary.get("inference_flow") if isinstance(summary.get("inference_flow"), list) else [])
    spec.setdefault("feedback_loops", [item for item in spec.get("relations", []) if isinstance(item, dict) and "feedback" in str(item.get("type") or "").casefold()])
    allowed_topologies = {"linear", "branch", "feedback", "multimodal", "dense_multiframe", "unknown"}
    if str(spec.get("topology") or "") not in allowed_topologies:
        spec["topology"] = _infer_topology(spec)
    completion_report["exact_visible_entity_groundings"] = _ground_exact_visible_entities(spec, parsed)
    _repair_cross_script_terminology(spec, parsed)
    labels = []
    terminology = spec.get("terminology") if isinstance(spec.get("terminology"), dict) else {}
    labels.extend(str(value).strip() for value in terminology.values() if str(value).strip())
    for field in ("inputs", "modules", "outputs", "innovations"):
        for item in spec.get(field, []) if isinstance(spec.get(field), list) else []:
            if isinstance(item, dict) and _item_label(item):
                labels.append(_item_label(item))
    spec["required_labels"] = list(dict.fromkeys(labels))
    raw_uncertainties = list(summary.get("unknowns", []) if isinstance(summary.get("unknowns"), list) else [])
    raw_uncertainties.extend(
        f"Dropped unresolved relation {value} because its endpoint was not declared."
        for value in completion_report.get("removed_unresolved_relations", [])
    )
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
    if parsed.get("extraction_report", {}).get("semantic_scope") == "sampled_pages_only":
        uncertainties.append("The source is a long scanned document; only scheduled sample pages were OCRed, so unprocessed pages may contain additional scientific details.")
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


def merge_review_grounded_contract(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    primary_spec = primary.get("figure_specification") if isinstance(primary.get("figure_specification"), dict) else {}
    fallback_spec = fallback.get("figure_specification") if isinstance(fallback.get("figure_specification"), dict) else {}
    endpoint_remap: dict[str, str] = {}
    for field in ("inputs", "modules", "outputs", "innovations", "must_show", "relations"):
        combined = list(primary_spec.get(field, []) if isinstance(primary_spec.get(field), list) else [])
        if field == "relations":
            keys = {(str(item.get("source")), str(item.get("target")), str(item.get("type"))) for item in combined if isinstance(item, dict)}
            for item in fallback_spec.get(field, []) if isinstance(fallback_spec.get(field), list) else []:
                if not isinstance(item, dict):
                    continue
                merged_relation = dict(item)
                merged_relation["source"] = endpoint_remap.get(str(item.get("source")), str(item.get("source")))
                merged_relation["target"] = endpoint_remap.get(str(item.get("target")), str(item.get("target")))
                key = (str(merged_relation.get("source")), str(merged_relation.get("target")), str(merged_relation.get("type")))
                if key and key not in keys:
                    combined.append(merged_relation)
                    keys.add(key)
        else:
            by_id = {_item_id(item, field, index).casefold(): _item_id(item, field, index) for index, item in enumerate(combined) if isinstance(item, dict)}
            by_label = {_item_label(item).casefold(): _item_id(item, field, index) for index, item in enumerate(combined) if isinstance(item, dict) and _item_label(item)}
            for index, item in enumerate(fallback_spec.get(field, []) if isinstance(fallback_spec.get(field), list) else []):
                if not isinstance(item, dict):
                    continue
                raw_item_id = _item_id(item, field, index)
                item_id = raw_item_id.casefold()
                label = _item_label(item).casefold()
                if item_id in by_id:
                    endpoint_remap[raw_item_id] = by_id[item_id]
                elif label and label in by_label:
                    endpoint_remap[raw_item_id] = by_label[label]
                else:
                    combined.append(item)
                    endpoint_remap[raw_item_id] = raw_item_id
                    by_id[item_id] = raw_item_id
                    if label:
                        by_label[label] = raw_item_id
        primary_spec[field] = combined
    terminology = dict(fallback_spec.get("terminology") if isinstance(fallback_spec.get("terminology"), dict) else {})
    terminology.update(primary_spec.get("terminology") if isinstance(primary_spec.get("terminology"), dict) else {})
    primary_spec["terminology"] = terminology
    primary_spec["forbidden_inventions"] = list(dict.fromkeys(
        list(primary_spec.get("forbidden_inventions", []) if isinstance(primary_spec.get("forbidden_inventions"), list) else [])
        + list(fallback_spec.get("forbidden_inventions", []) if isinstance(fallback_spec.get("forbidden_inventions"), list) else [])
    ))
    primary["figure_specification"] = primary_spec
    primary_design = primary.get("design_plan") if isinstance(primary.get("design_plan"), dict) else {}
    fallback_order = fallback.get("design_plan", {}).get("reading_order", []) if isinstance(fallback.get("design_plan"), dict) else []
    primary_design["reading_order"] = list(dict.fromkeys(list(primary_design.get("reading_order", [])) + list(fallback_order)))
    primary["design_plan"] = primary_design
    return primary


def _paper_review_from_plan(plan: dict[str, Any], selected_domain: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("paper_summary") if isinstance(plan.get("paper_summary"), dict) else {}
    spec = plan.get("figure_specification") if isinstance(plan.get("figure_specification"), dict) else {}
    def fact(item: Any, item_id: str) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {"id": item_id, "statement": str(item or "unknown"), "evidence_ids": [], "status": "unknown"}
        return {
            "id": str(item.get("id") or item_id),
            "statement": str(item.get("statement") or item.get("text") or item.get("name") or "unknown"),
            "visible_label": str(item.get("visible_label") or item.get("name") or item.get("text") or item.get("statement") or ""),
            "evidence_ids": list(item.get("evidence_ids", [])),
            "status": str(item.get("status") or "required"),
            "importance": str(item.get("importance") or "high"),
            "confidence": float(item.get("confidence", 1.0) or 0.0),
            "must_appear_in_figure": True,
            "visual_role": str(item.get("role") or "module"),
        }
    return {
        "summary": "Compact paper review derived from the fast VLM figure contract.",
        "schema_version": "2.0-fast",
        "paper_identity": {"title": summary.get("title"), "paper_type": summary.get("paper_type", "unknown")},
        "domain_profile": selected_domain.get("id"),
        "research_questions": [fact(spec.get("research_problem") or summary.get("research_problem"), "research_problem")],
        "central_claims": [fact(spec.get("central_claim") or summary.get("central_claim"), "central_claim")],
        "inputs": [fact(item, f"input_{index}") for index, item in enumerate(spec.get("inputs", [])) if isinstance(item, dict)],
        "outputs": [fact(item, f"output_{index}") for index, item in enumerate(spec.get("outputs", [])) if isinstance(item, dict)],
        "research_objects": [],
        "concepts": [],
        "modules": [fact(item, f"module_{index}") for index, item in enumerate(spec.get("modules", [])) if isinstance(item, dict)],
        "relations": [
            {**fact(item, f"relation_{index}"), "source_id": item.get("source"), "target_id": item.get("target"), "relation_type": item.get("type", "data_flow")}
            for index, item in enumerate(spec.get("relations", [])) if isinstance(item, dict)
        ],
        "contributions": [],
        "innovations": [fact(item, f"innovation_{index}") for index, item in enumerate(spec.get("innovations", [])) if isinstance(item, dict)],
        "workflows": {
            "training": [fact(item, f"training_{index}") for index, item in enumerate(spec.get("training_flow", []))],
            "inference": [fact(item, f"inference_{index}") for index, item in enumerate(spec.get("inference_flow", []))],
        },
        "experiments": {},
        "assumptions": [],
        "limitations": [],
        "results": [],
        "terminology": [],
        "forbidden_inventions": [{"id": f"forbidden_{index}", "statement": str(value), "evidence_ids": []} for index, value in enumerate(spec.get("forbidden_inventions", []))],
        "unknowns": list(spec.get("uncertainties", [])),
    }


def _fast_cache_path(parsed: dict[str, Any], model: str, preferences: dict[str, Any]) -> Path:
    signature = json.dumps({"version": 29, "document_cache_version": DOCUMENT_CACHE_VERSION, "model": model, "aspect_ratio": preferences.get("aspect_ratio"), "language": preferences.get("language")}, sort_keys=True).encode("utf-8")
    variant = hashlib.sha256(signature).hexdigest()[:16]
    root = Path(os.getenv("RFS_CACHE_DIR", "").strip() or (Path.home() / ".cache" / "research-figure-studio"))
    return root / "paper_contracts" / str(parsed.get("source_sha256")) / variant / "fast_plan.json"


def _semantic_cache_safe(parsed: dict[str, Any]) -> bool:
    report = parsed.get("extraction_report", {})
    return bool(report.get("scientific_scope_complete", True) and report.get("ocr_run_complete", True))


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
    fast_mode: bool = False,
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
    provider_deadline_at = deadline_at - 15.0
    ocr_rescue_min_remaining = 90.0 if fast_mode and planner_mode == "vlm" and deadline <= 240 else 45.0
    parsed = None if ocr_adapter else read_document_cache(archived_paper, ocr_engine=ocr_engine, ocr_lang=ocr_lang)
    document_cache_hit = parsed is not None
    if parsed is None:
        parsed = parse_paper(archived_paper, deadline_at=deadline_at, ocr_engine=ocr_engine, ocr_lang=ocr_lang, ocr_adapter=ocr_adapter, ocr_rescue_min_remaining=ocr_rescue_min_remaining)
        if not ocr_adapter:
            write_document_cache(archived_paper, parsed, ocr_engine=ocr_engine, ocr_lang=ocr_lang)
    document_preparation_seconds = round(time.monotonic() - started, 3)
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
    if fast_mode:
        remaining = max(0, int(provider_deadline_at - time.monotonic()))
        effective_mode = planner_mode if remaining >= 25 else "heuristic"
        cache_path = _fast_cache_path(parsed, str(planner_model or ""), preferences)
        if cache_path.exists() and effective_mode == "vlm" and _semantic_cache_safe(parsed):
            plan = read_json(cache_path)
            planner_metadata = {"requested_mode": "vlm", "mode": "vlm", "model": planner_model, "warning": None, "prompt": "", "cached": True}
        else:
            plan, planner_metadata = plan_fast_paper_contract(
                parsed,
                preferences,
                mode=effective_mode,
                model=planner_model,
                timeout_seconds=min(35, remaining),
                retries=2,
                evidence_max_chars=36000,
                deadline_at=provider_deadline_at,
            )
        if planner_metadata.get("mode") == "vlm":
            paper_review = _paper_review_from_plan(plan, selected_domain)
            review_metadata = {"summary": "Paper review derived from the successful fast VLM plan.", "requested_mode": planner_mode, "mode": "derived_from_vlm_plan", "model": planner_metadata.get("model"), "warning": None, "prompt": ""}
        else:
            remaining = max(0, int(provider_deadline_at - time.monotonic()))
            review_mode = planner_mode if remaining >= 25 else "heuristic"
            paper_review, review_metadata = build_paper_review(
                parsed,
                selected_domain,
                mode=review_mode,
                model=planner_model,
                timeout_seconds=max(1, min(35, remaining)),
                retries=1,
                evidence_max_chars=36000,
                deadline_at=provider_deadline_at,
            )
            if review_metadata.get("mode") == "vlm":
                plan = build_review_grounded_plan(parsed, preferences, paper_review)
                planner_metadata = {**planner_metadata, "mode": "review_grounded_vlm", "model": review_metadata.get("model"), "warning": planner_metadata.get("warning")}
    else:
        remaining = max(0, int(provider_deadline_at - time.monotonic()))
        effective_mode = planner_mode if remaining >= 30 else "heuristic"
        paper_review, review_metadata = build_paper_review(parsed, selected_domain, mode=effective_mode, model=planner_model, timeout_seconds=max(1, min(35, remaining)), retries=1, deadline_at=provider_deadline_at)
        remaining = max(0, int(provider_deadline_at - time.monotonic()))
        planning_mode = effective_mode if remaining >= 25 else "heuristic"
        plan, planner_metadata = plan_paper_image(
            parsed,
            preferences,
            mode=planning_mode,
            model=planner_model,
            reference_images=archived_positive + archived_negative,
            paper_review=paper_review,
            timeout_seconds=max(1, min(35, remaining)),
            retries=1,
            deadline_at=provider_deadline_at,
        )
        fallback_plan = build_review_grounded_plan(parsed, preferences, paper_review)
        if review_metadata.get("mode") == "vlm":
            plan = merge_review_grounded_contract(plan, fallback_plan)
    review_prompt = review_metadata.pop("prompt", "")
    write_text(root / "prompts" / "paper_review_prompt.txt", review_prompt)
    write_json(root / "paper_review_metadata.json", review_metadata)
    write_json(root / "paper_review.json", paper_review)
    coverage = validate_review_coverage(paper_review, parsed, selected_domain, strict=False)
    write_json(root / "review_coverage_report.json", coverage)
    planning_prompt = planner_metadata.pop("prompt")
    write_text(root / "prompts" / "planning_prompt.txt", planning_prompt)
    write_json(root / "planning_metadata.json", {"summary": "Planner execution metadata.", **planner_metadata})
    expand_plan_evidence(plan, paper_review, parsed)
    normalize_figure_contract(plan, parsed)
    completion_report = plan.get("contract_completion_report") if isinstance(plan.get("contract_completion_report"), dict) else {}
    write_json(root / "contract_completion_report.json", completion_report)
    for name in ("paper_summary", "figure_specification", "design_plan", "layout_intent", "visual_metaphors", "style_plan"):
        write_json(root / f"{name}.json", plan[name])
    planning_validation = validate_plan_grounding(plan, parsed)
    write_json(root / "planning_validation_report.json", planning_validation)
    if fast_mode and planning_validation.get("ok") and planner_metadata.get("mode") in {"vlm", "review_grounded_vlm"} and _semantic_cache_safe(parsed):
        write_json(cache_path, plan)
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
    scientific_scope_complete = bool(parsed["extraction_report"].get("scientific_scope_complete", True))
    production_ready = bool((review_metadata.get("mode") == "vlm" or planner_metadata.get("mode") == "vlm") and planning_validation.get("ok") and not deadline_reached and scientific_scope_complete)
    has_warning = bool(planner_metadata.get("warning") or review_metadata.get("warning") or parsed["extraction_report"].get("status") == "warning")
    status = "complete" if production_ready and not has_warning else "completed_with_warnings"
    contract_source = "cache" if planner_metadata.get("cached") else "vlm" if planner_metadata.get("mode") == "vlm" else "vlm_review_deterministic_compile" if planner_metadata.get("mode") == "review_grounded_vlm" else "deterministic_evidence_rules"
    source_extraction_seconds = float(parsed["extraction_report"].get("elapsed_seconds") or 0.0)
    extraction_seconds = 0.0 if document_cache_hit else source_extraction_seconds
    planner_provider = planner_metadata.get("provider") if isinstance(planner_metadata.get("provider"), dict) else {}
    review_provider = review_metadata.get("provider") if isinstance(review_metadata.get("provider"), dict) else {}
    provider_calls = [item for item in (planner_provider, review_provider) if item.get("attempts")]
    provider_summary = {
        "planner": planner_provider,
        "review": review_provider,
        "attempts": sum(int(item.get("attempts") or 0) for item in provider_calls),
        "retries_used": sum(int(item.get("retries_used") or 0) for item in provider_calls),
        "success": any(bool(item.get("success")) for item in provider_calls) if provider_calls else None,
        "successful_call_count": sum(bool(item.get("success")) for item in provider_calls),
        "call_count": len(provider_calls),
        "elapsed_seconds": round(sum(float(item.get("elapsed_seconds") or 0.0) for item in provider_calls), 3),
        "failure_categories": list(dict.fromkeys(category for item in provider_calls for category in (item.get("failure_categories") or []))),
    }
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
        "contract_source": contract_source,
        "cache_hit": bool(planner_metadata.get("cached")),
        "document_cache_hit": document_cache_hit,
        "extraction_quality": {
            "pdf_type": parsed["extraction_report"].get("pdf_type"),
            "page_count": parsed["extraction_report"].get("page_count"),
            "readable_page_ratio": parsed["extraction_report"].get("readable_page_ratio"),
            "semantic_scope": parsed["extraction_report"].get("semantic_scope", "full_document"),
            "scientific_scope_complete": scientific_scope_complete,
            "sampled_scan_ready": parsed["extraction_report"].get("sampled_scan_ready", False),
            "evidence_page_coverage_ratio": parsed["extraction_report"].get("evidence_page_coverage_ratio"),
            "evidence_char_count": parsed["extraction_report"].get("evidence_char_count"),
            "max_column_count": parsed["extraction_report"].get("max_column_count"),
            "multi_column_page_count": parsed["extraction_report"].get("multi_column_page_count"),
            "rotated_pages": parsed["extraction_report"].get("rotated_pages", []),
            "section_count": parsed["extraction_report"].get("section_count", 0),
            "typographic_heading_count": parsed["extraction_report"].get("typographic_heading_count", 0),
            "merged_heading_line_count": parsed["extraction_report"].get("merged_heading_line_count", 0),
            "figure_caption_count": parsed["extraction_report"].get("figure_caption_count", 0),
            "table_caption_count": parsed["extraction_report"].get("table_caption_count", 0),
            "section_coverage": parsed["extraction_report"].get("section_coverage", {}),
            "missing_priority_sections": [name for name, present in parsed["extraction_report"].get("section_coverage", {}).items() if not present],
            "ocr_candidate_count": len(parsed["extraction_report"].get("ocr_candidate_pages", [])),
            "ocr_scheduled_count": len(parsed["extraction_report"].get("ocr_priority_pages", [])),
            "ocr_completed_count": len(parsed["extraction_report"].get("ocr_pages", [])),
            "ocr_attempted_count": len(parsed["extraction_report"].get("ocr_attempted_pages", [])),
            "ocr_schedule_complete": parsed["extraction_report"].get("ocr_schedule_complete", True),
            "ocr_run_complete": parsed["extraction_report"].get("ocr_run_complete", True),
            "ocr_worker_count": parsed["extraction_report"].get("ocr_worker_count", 1),
            "ocr_rescue_min_remaining_seconds": parsed["extraction_report"].get("ocr_rescue_min_remaining_seconds", 45.0),
            "repeated_margin_noise_removed_count": parsed["extraction_report"].get("repeated_margin_noise_removed_count", 0),
            "native_hyphenation_repair_count": parsed["extraction_report"].get("native_hyphenation_repair_count", 0),
            "ocr_margin_noise_removed_count": parsed["extraction_report"].get("ocr_margin_noise_removed_count", 0),
            "ocr_spacing_repair_count": parsed["extraction_report"].get("ocr_spacing_repair_count", 0),
        },
        "provider": provider_summary,
        "contract_completion": {
            "overview_term_coverage": completion_report.get("overview_term_coverage"),
            "added_entity_count": len(completion_report.get("added_entities", [])),
            "added_relation_count": len(completion_report.get("added_relations", [])),
        },
        "planner_warning": planner_metadata.get("warning"),
        "review_warning": review_metadata.get("warning"),
        "topology": plan["figure_specification"].get("topology"),
        "module_count": len(plan["figure_specification"].get("modules", [])),
        "relation_count": len(plan["figure_specification"].get("relations", [])),
        "stage_timings": {
            "document_preparation_seconds": document_preparation_seconds,
            "document_extraction_seconds": extraction_seconds,
            "cached_source_extraction_seconds": source_extraction_seconds if document_cache_hit else None,
            "semantic_compilation_seconds": round(max(0.0, elapsed - document_preparation_seconds), 3),
            "total_seconds": elapsed,
        },
        "uncertainties": plan["figure_specification"].get("uncertainties", []),
        "artifacts": ["paper.md", "document_model.json", "extraction_report.json", "section_index.json", "section_summary.md", "key_evidence.json", "paper_review.json", "figure_specification.json", "contract_completion_report.json", "planning_validation_report.json", "image_prompt.md", "overlay_spec.json", "run_report.json"],
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
    if not kwargs.get("planner_model"):
        kwargs["planner_model"] = os.getenv("RFS_FAST_FRAMEWORK_MODEL", "").strip() or "gemini-2.5-flash"
    kwargs["fast_mode"] = True
    prepared = prepare_paper_figure_contract(**kwargs)
    internal = {"root", "parsed", "preferences", "paper_review", "review_metadata", "selected_domain", "plan", "planner_metadata", "archived_positive", "archived_negative", "planning_validation"}
    return {key: value for key, value in prepared.items() if key not in internal}
