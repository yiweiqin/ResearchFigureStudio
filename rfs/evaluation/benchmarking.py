from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from ..utils import ensure_dir, read_json, write_json, write_text


SUITES = {"paper-to-image", "image-to-ppt"}


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = read_json(path)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _mean(values: list[float]) -> float:
    return round(sum(values) / max(1, len(values)), 4)


def _clamp(value: object) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except Exception:
        return 0.0


def _threshold_failures(metrics: dict, thresholds: dict) -> list[str]:
    maximum_metrics = {"hallucination_count", "forbidden_content_count", "full_slide_image_count", "blocking_visual_issue_count"}
    failures = []
    for key, threshold in thresholds.items():
        value = metrics.get(key)
        if not isinstance(value, (int, float)) or not isinstance(threshold, (int, float)):
            continue
        if key in maximum_metrics and float(value) > float(threshold):
            failures.append(f"{key}={value} above maximum {threshold}")
        elif key not in maximum_metrics and float(value) < float(threshold):
            failures.append(f"{key}={value} below minimum {threshold}")
    return failures


def validate_benchmark_case(case_dir: str | Path) -> dict[str, Any]:
    root = Path(case_dir).resolve()
    case = _load(root / "case.json")
    errors: list[str] = []
    warnings: list[str] = []
    suite = str(case.get("suite") or "")
    if suite not in SUITES:
        errors.append(f"case.json suite must be one of {sorted(SUITES)}")
    if not str(case.get("case_id") or "").strip():
        errors.append("case.json requires case_id")
    if not isinstance(case.get("thresholds"), dict):
        errors.append("case.json requires thresholds object")

    required_files = ["case.json"]
    if suite == "paper-to-image":
        required_files.extend([str(case.get("paper") or "paper.md"), str(case.get("expected_semantics") or "expected_semantics.json")])
        expected = _load(root / str(case.get("expected_semantics") or "expected_semantics.json"))
        if not expected.get("entities"):
            errors.append("expected_semantics.json requires entities")
        if not isinstance(expected.get("relations"), list):
            errors.append("expected_semantics.json requires relations list")
        if not isinstance(expected.get("forbidden_labels", []), list):
            errors.append("expected_semantics.json forbidden_labels must be a list")
    elif suite == "image-to-ppt":
        required_files.extend([str(case.get("reference_image") or "reference.png"), str(case.get("expected_objects") or "expected_objects.json")])
        expected = _load(root / str(case.get("expected_objects") or "expected_objects.json"))
        if not isinstance(expected.get("objects"), list):
            errors.append("expected_objects.json requires objects list")
        if not isinstance(expected.get("relations", []), list):
            errors.append("expected_objects.json relations must be a list")

    for relative in required_files:
        if relative and not (root / relative).exists():
            errors.append(f"missing required file: {relative}")
    references = case.get("positive_references", []) + case.get("negative_references", [])
    for relative in references:
        if not (root / str(relative)).exists():
            warnings.append(f"missing optional reference: {relative}")

    return {
        "summary": "Benchmark case validation report.",
        "ok": not errors,
        "case_dir": str(root),
        "case_id": case.get("case_id"),
        "suite": suite,
        "errors": errors,
        "warnings": warnings,
    }


def list_benchmark_cases(benchmarks_root: str | Path, suite: str | None = None) -> dict[str, Any]:
    root = Path(benchmarks_root).resolve()
    cases = []
    suites = [suite] if suite else sorted(SUITES)
    for suite_name in suites:
        case_root = root / suite_name / "cases"
        if not case_root.exists():
            continue
        for case_dir in sorted(path for path in case_root.iterdir() if path.is_dir()):
            validation = validate_benchmark_case(case_dir)
            cases.append({
                "case_id": validation.get("case_id") or case_dir.name,
                "suite": suite_name,
                "case_dir": str(case_dir),
                "valid": validation["ok"],
                "errors": validation["errors"],
            })
    return {"summary": "Available ResearchFigureStudio benchmark cases.", "benchmarks_root": str(root), "cases": cases}


def _select_candidate_review(run: Path) -> dict:
    report = _load(run / "candidate_review.json")
    candidates = [item for item in report.get("candidates", []) if isinstance(item, dict)]
    selected_id = report.get("selected_candidate_id")
    selected = next((item for item in candidates if item.get("candidate_id") == selected_id), None)
    if not selected and candidates:
        selected = max(candidates, key=lambda item: float(item.get("score") or 0.0))
    return selected.get("review", {}) if isinstance(selected, dict) else {}


def score_paper_to_image(case_dir: str | Path, run_dir: str | Path) -> dict[str, Any]:
    case_root, run = Path(case_dir).resolve(), Path(run_dir).resolve()
    case = _load(case_root / "case.json")
    expected = _load(case_root / str(case.get("expected_semantics") or "expected_semantics.json"))
    review = _select_candidate_review(run)
    benchmark_review = _load(run / "benchmark_review.json")
    if benchmark_review:
        review = {**review, **benchmark_review}

    scientific = review.get("scientific", {}) if isinstance(review.get("scientific"), dict) else {}
    ocr = review.get("ocr", {}) if isinstance(review.get("ocr"), dict) else {}
    aesthetic = review.get("aesthetic", {}) if isinstance(review.get("aesthetic"), dict) else {}
    clarity = review.get("clarity", {}) if isinstance(review.get("clarity"), dict) else {}
    information = review.get("information", {}) if isinstance(review.get("information"), dict) else {}
    stability = review.get("stability", {}) if isinstance(review.get("stability"), dict) else {}

    expected_entities = [item for item in expected.get("entities", []) if isinstance(item, dict) and item.get("required", True)]
    expected_relations = [item for item in expected.get("relations", []) if isinstance(item, dict) and item.get("required", True)]
    missing_entities = scientific.get("missing_modules", []) or benchmark_review.get("missing_entities", [])
    missing_relations = scientific.get("missing_relations", []) or benchmark_review.get("missing_relations", [])
    invented = scientific.get("invented_items", []) or benchmark_review.get("invented_items", [])
    forbidden_found = ocr.get("forbidden_labels_found", []) or benchmark_review.get("forbidden_labels_found", [])
    missing_labels = ocr.get("missing_labels", []) or benchmark_review.get("missing_labels", [])
    misspelled = ocr.get("misspelled_labels", []) or benchmark_review.get("misspelled_labels", [])

    entity_recall = _clamp((len(expected_entities) - len(missing_entities)) / max(1, len(expected_entities)))
    relation_recall = _clamp((len(expected_relations) - len(missing_relations)) / max(1, len(expected_relations)))
    exact_label_rate = _clamp((len(expected_entities) - len(missing_labels) - len(misspelled)) / max(1, len(expected_entities)))
    scientific_score = _clamp(scientific.get("score", _mean([entity_recall, relation_recall])))
    aesthetic_dimensions = [aesthetic.get(key) for key in ("hierarchy", "balance", "whitespace", "color", "icon_consistency", "readability") if aesthetic.get(key) is not None]
    aesthetic_score = _clamp(aesthetic.get("score", _mean([_clamp(value) for value in aesthetic_dimensions])))
    clarity_score = _clamp(clarity.get("score", aesthetic.get("readability", 0.0)))
    information_score = _clamp(information.get("score", information.get("coverage", scientific_score)))
    stability_score = _clamp(stability.get("production_pass_rate", stability.get("score", 0.0)))
    hard_failures = list(review.get("hard_errors", []))
    if not scientific or not aesthetic or scientific.get("engineering_only") or aesthetic.get("engineering_only"):
        hard_failures.append("frozen benchmark judge did not provide scientific and aesthetic sections")
    if invented:
        hard_failures.append("invented scientific content")
    if forbidden_found:
        hard_failures.append("forbidden labels found")
    if relation_recall < 1.0:
        hard_failures.append("required relations missing or incorrect")
    if exact_label_rate < 1.0:
        hard_failures.append("required labels missing or misspelled")

    metrics = {
        "entity_recall": entity_recall,
        "relation_recall": relation_recall,
        "exact_label_rate": exact_label_rate,
        "scientific_score": scientific_score,
        "information_score": information_score,
        "clarity_score": clarity_score,
        "aesthetic_score": aesthetic_score,
        "stability_score": stability_score,
        "hallucination_count": len(invented),
        "forbidden_content_count": len(forbidden_found),
    }
    thresholds = case.get("thresholds", {})
    threshold_failures = _threshold_failures(metrics, thresholds)
    total_score = round(0.40 * scientific_score + 0.15 * information_score + 0.15 * clarity_score + 0.20 * aesthetic_score + 0.10 * stability_score, 4)
    return {
        "summary": "Paper-to-image benchmark score.",
        "suite": "paper-to-image",
        "case_id": case.get("case_id"),
        "case_dir": str(case_root),
        "run_dir": str(run),
        "metrics": metrics,
        "total_score": total_score,
        "hard_failures": sorted(set(hard_failures)),
        "threshold_failures": threshold_failures,
        "passed": not hard_failures and not threshold_failures,
        "policy": "scientific, relation, terminology, and hallucination failures cannot be offset by aesthetics",
    }


def _image_similarity(reference: Path, preview: Path) -> dict[str, float | None]:
    if not reference.exists() or not preview.exists():
        return {"pixel_similarity": None, "edge_similarity": None, "color_similarity": None}
    with Image.open(reference) as ref_image, Image.open(preview) as out_image:
        ref = ref_image.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)
        out = out_image.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)
    difference = ImageChops.difference(ref, out)
    rms = math.sqrt(sum(value * value for value in ImageStat.Stat(difference).rms) / 3.0)
    pixel_similarity = _clamp(1.0 - rms / 255.0)
    ref_edge = ref.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda value: 255 if value > 32 else 0)
    out_edge = out.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda value: 255 if value > 32 else 0)
    edge_diff = ImageChops.difference(ref_edge, out_edge)
    edge_similarity = _clamp(1.0 - ImageStat.Stat(edge_diff).mean[0] / 255.0)
    ref_mean, out_mean = ImageStat.Stat(ref).mean, ImageStat.Stat(out).mean
    color_error = sum(abs(a - b) for a, b in zip(ref_mean, out_mean)) / (3.0 * 255.0)
    return {"pixel_similarity": pixel_similarity, "edge_similarity": edge_similarity, "color_similarity": _clamp(1.0 - color_error)}


def _ppt_editability(pptx_path: Path) -> dict[str, Any]:
    if not pptx_path.exists():
        return {"status": "missing", "full_slide_image_count": 0, "text_shape_count": 0, "connector_count": 0, "shape_count": 0}
    presentation = Presentation(str(pptx_path))
    full_slide_images = 0
    text_shapes = 0
    connectors = 0
    shapes = 0
    slide_width, slide_height = float(presentation.slide_width), float(presentation.slide_height)
    for slide in presentation.slides:
        for shape in slide.shapes:
            shapes += 1
            if getattr(shape, "has_text_frame", False) and str(getattr(shape, "text", "")).strip():
                text_shapes += 1
            if shape.shape_type == MSO_SHAPE_TYPE.LINE:
                connectors += 1
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                coverage = float(shape.width) * float(shape.height) / max(1.0, slide_width * slide_height)
                if coverage >= 0.90:
                    full_slide_images += 1
    return {
        "status": "pass" if full_slide_images == 0 else "blocked",
        "full_slide_image_count": full_slide_images,
        "text_shape_count": text_shapes,
        "connector_count": connectors,
        "shape_count": shapes,
    }


def _bbox_iou(left: dict, right: dict) -> float:
    lx0, ly0 = float(left.get("x", 0)), float(left.get("y", 0))
    lx1, ly1 = lx0 + float(left.get("w", 0)), ly0 + float(left.get("h", 0))
    rx0, ry0 = float(right.get("x", 0)), float(right.get("y", 0))
    rx1, ry1 = rx0 + float(right.get("w", 0)), ry0 + float(right.get("h", 0))
    intersection = max(0.0, min(lx1, rx1) - max(lx0, rx0)) * max(0.0, min(ly1, ry1) - max(ly0, ry0))
    union = max(0.000001, float(left.get("w", 0)) * float(left.get("h", 0)) + float(right.get("w", 0)) * float(right.get("h", 0)) - intersection)
    return intersection / union


def _center_error(left: dict, right: dict) -> float:
    lx = float(left.get("x", 0)) + float(left.get("w", 0)) / 2
    ly = float(left.get("y", 0)) + float(left.get("h", 0)) / 2
    rx = float(right.get("x", 0)) + float(right.get("w", 0)) / 2
    ry = float(right.get("y", 0)) + float(right.get("h", 0)) / 2
    return math.sqrt((lx - rx) ** 2 + (ly - ry) ** 2)


def _match_expected_objects(expected_objects: list[dict], geometry: dict) -> tuple[list[dict], dict[str, str]]:
    actual = []
    for collection, object_type in (("panels", "panel"), ("cards", "card"), ("slots", "asset")):
        actual.extend({**item, "benchmark_type": object_type} for item in geometry.get(collection, []) if isinstance(item, dict) and isinstance(item.get("bbox_percent"), dict))
    unmatched = list(actual)
    matches = []
    id_mapping: dict[str, str] = {}
    for expected in expected_objects:
        expected_box = expected.get("bbox_percent") if isinstance(expected.get("bbox_percent"), dict) else {}
        expected_type = str(expected.get("type") or "")
        same_id = next((item for item in unmatched if str(item.get("id")) == str(expected.get("id"))), None)
        candidates = [item for item in unmatched if expected_type in {"", str(item.get("benchmark_type"))}]
        if not candidates:
            candidates = unmatched
        chosen = same_id or max(candidates, key=lambda item: _bbox_iou(expected_box, item["bbox_percent"]), default=None)
        if not chosen:
            matches.append({"expected_id": expected.get("id"), "status": "unmatched", "iou": 0.0, "center_error": 1.0})
            continue
        unmatched.remove(chosen)
        iou = _bbox_iou(expected_box, chosen["bbox_percent"])
        center_error = _center_error(expected_box, chosen["bbox_percent"])
        id_mapping[str(expected.get("id"))] = str(chosen.get("id"))
        matches.append({
            "expected_id": expected.get("id"),
            "actual_id": chosen.get("id"),
            "expected_type": expected_type,
            "actual_type": chosen.get("benchmark_type"),
            "iou": round(iou, 4),
            "center_error": round(center_error, 4),
            "status": "matched" if iou >= 0.30 else "low_overlap",
        })
    return matches, id_mapping


def score_image_to_ppt(case_dir: str | Path, run_dir: str | Path) -> dict[str, Any]:
    case_root, run = Path(case_dir).resolve(), Path(run_dir).resolve()
    case = _load(case_root / "case.json")
    expected = _load(case_root / str(case.get("expected_objects") or "expected_objects.json"))
    reference = case_root / str(case.get("reference_image") or "reference.png")
    preview = run / str(case.get("preview") or "rebuild_preview.png")
    pptx = run / str(case.get("pptx") or "editable_composition.pptx")
    similarity = _image_similarity(reference, preview)
    editability = _ppt_editability(pptx)
    visual = _load(run / "rebuild_visual_quality_report.json")
    semantic = _load(run / "semantic_binding_report.json")
    composition = _load(run / "composition_quality_report.json")
    alignment = _load(run / "text_alignment_report.json")
    geometry = _load(run / "reference_geometry.json")

    expected_objects = [item for item in expected.get("objects", []) if isinstance(item, dict)]
    expected_relations = [item for item in expected.get("relations", []) if isinstance(item, dict)]
    object_matches, id_mapping = _match_expected_objects(expected_objects, geometry)
    object_coverage = _clamp(sum(1 for item in object_matches if item["status"] == "matched") / max(1, len(expected_objects))) if expected_objects else 1.0
    mean_object_iou = _mean([float(item["iou"]) for item in object_matches]) if object_matches else 1.0
    mean_center_error = _mean([float(item["center_error"]) for item in object_matches]) if object_matches else 0.0
    actual_relations = {
        (str(item.get("source_id") or item.get("source") or ""), str(item.get("target_id") or item.get("target") or ""))
        for item in composition.get("arrows", [])
        if isinstance(item, dict)
    }
    matched_relations = 0
    for relation in expected_relations:
        source = id_mapping.get(str(relation.get("source")))
        target = id_mapping.get(str(relation.get("target")))
        if source and target and (source, target) in actual_relations:
            matched_relations += 1
    relation_coverage = _clamp(matched_relations / max(1, len(expected_relations))) if expected_relations else 1.0
    max_text_delta = max((float(item.get("center_delta_percent") or 0.0) for item in alignment.get("items", []) if isinstance(item, dict)), default=0.0)
    text_alignment_score = _clamp(1.0 - max_text_delta / 0.10)
    blocking_visual_issues = int(visual.get("blocking_issue_count") or 0)
    semantic_binding_score = _clamp(semantic.get("mapped_entity_count", 0) / max(1, semantic.get("entity_count", 0))) if semantic else 1.0
    editable_score = 0.0 if editability["status"] == "blocked" else _clamp((min(1, editability["text_shape_count"]) + min(1, editability["connector_count"]) + 1) / 3)
    fidelity_values = [value for value in similarity.values() if isinstance(value, float)]
    render_fidelity = _mean(fidelity_values) if fidelity_values else 0.0
    metrics = {
        **similarity,
        "render_fidelity": render_fidelity,
        "object_coverage": object_coverage,
        "mean_object_iou": mean_object_iou,
        "mean_center_error": mean_center_error,
        "relation_coverage": relation_coverage,
        "text_alignment_score": text_alignment_score,
        "semantic_binding_score": semantic_binding_score,
        "editability_score": editable_score,
        "full_slide_image_count": editability["full_slide_image_count"],
        "blocking_visual_issue_count": blocking_visual_issues,
    }
    hard_failures = []
    if editability["full_slide_image_count"]:
        hard_failures.append("full-slide reference image detected")
    if blocking_visual_issues:
        hard_failures.append("blocking visual issues remain")
    thresholds = case.get("thresholds", {})
    threshold_failures = _threshold_failures(metrics, thresholds)
    total_score = round(0.40 * render_fidelity + 0.20 * object_coverage + 0.15 * relation_coverage + 0.10 * text_alignment_score + 0.15 * editable_score, 4)
    return {
        "summary": "Image-to-editable-PPT benchmark score.",
        "suite": "image-to-ppt",
        "case_id": case.get("case_id"),
        "case_dir": str(case_root),
        "run_dir": str(run),
        "metrics": metrics,
        "editability": editability,
        "object_matches": object_matches,
        "total_score": total_score,
        "hard_failures": hard_failures,
        "threshold_failures": threshold_failures,
        "passed": not hard_failures and not threshold_failures,
        "limitations": [
            "pixel, edge, and color similarity are baseline metrics; calibrated SSIM/LPIPS and region annotations remain future work",
            "mutation-based editability testing requires a dedicated render-after-edit harness",
        ],
    }


def score_benchmark_case(case_dir: str | Path, run_dir: str | Path, out: str | Path | None = None) -> dict[str, Any]:
    validation = validate_benchmark_case(case_dir)
    if not validation["ok"]:
        return {**validation, "passed": False}
    result = score_paper_to_image(case_dir, run_dir) if validation["suite"] == "paper-to-image" else score_image_to_ppt(case_dir, run_dir)
    target = ensure_dir(out or run_dir)
    write_json(target / "benchmark_result.json", result)
    lines = [
        "# Benchmark Result",
        "",
        f"- Suite: {result.get('suite')}",
        f"- Case: {result.get('case_id')}",
        f"- Passed: {result.get('passed')}",
        f"- Total score: {result.get('total_score')}",
        "",
        "## Metrics",
    ]
    lines.extend(f"- {key}: {value}" for key, value in result.get("metrics", {}).items())
    lines.extend(["", "## Hard failures"])
    lines.extend(f"- {item}" for item in result.get("hard_failures", []))
    lines.extend(["", "## Threshold failures"])
    lines.extend(f"- {item}" for item in result.get("threshold_failures", []))
    write_text(target / "benchmark_result.md", "\n".join(lines) + "\n")
    return result


def run_benchmark_case(case_dir: str | Path, out: str | Path) -> dict[str, Any]:
    validation = validate_benchmark_case(case_dir)
    if not validation["ok"]:
        return {**validation, "passed": False}
    root = Path(case_dir).resolve()
    target = ensure_dir(out).resolve()
    case = _load(root / "case.json")
    config = case.get("run_config", {}) if isinstance(case.get("run_config"), dict) else {}
    if validation["suite"] == "paper-to-image":
        from ..paper_to_image import run_paper_to_image

        workflow_result = run_paper_to_image(
            paper=root / str(case.get("paper") or "paper.md"),
            out=target,
            preferences_path=(root / str(case["preferences"])) if case.get("preferences") else None,
            positive_references=[str(root / str(path)) for path in case.get("positive_references", [])],
            negative_references=[str(root / str(path)) for path in case.get("negative_references", [])],
            planner_mode=str(config.get("planner_mode") or "heuristic"),
            asset_mode=str(config.get("image_asset_mode") or "placeholder"),
            candidates=int(config.get("image_candidates") or 1),
            aspect_ratio=str(config.get("aspect_ratio") or "auto"),
            language=str(config.get("language") or "English"),
            review_mode=str(config.get("review_mode") or "heuristic"),
            domain_profile=str(config.get("domain_profile") or "auto"),
            template=str(config.get("template") or "auto"),
            repair_rounds=int(config.get("repair_rounds") or 0),
            ocr_engine=str(config.get("ocr_engine") or "off"),
            ocr_lang=str(config.get("ocr_lang") or "en_ch"),
        )
    else:
        from ..editable_rebuild import rebuild_editable

        workflow_result = rebuild_editable(
            reference=root / str(case.get("reference_image") or "reference.png"),
            out=target,
            asset_mode=str(config.get("asset_mode") or "placeholder"),
            asset_policy=str(config.get("asset_policy") or "smart-api"),
            text_mode=str(config.get("text_mode") or "off"),
            layout_mode=str(config.get("layout_mode") or "heuristic"),
            control_mode=str(config.get("control_mode") or "heuristic"),
            design_plan_mode=str(config.get("design_plan_mode") or "heuristic"),
            export_preview=True,
            ocr_engine=str(config.get("ocr_engine") or "off"),
        )
    score = score_benchmark_case(root, target, target)
    result = {
        "summary": "Benchmark workflow and scoring completed.",
        "ok": bool(workflow_result.get("ok")),
        "suite": validation["suite"],
        "case_id": validation["case_id"],
        "out_dir": str(target),
        "workflow_result": workflow_result,
        "benchmark_result": score,
    }
    write_json(target / "benchmark_run.json", result)
    return result
