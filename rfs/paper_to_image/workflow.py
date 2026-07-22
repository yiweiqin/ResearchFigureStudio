from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..utils import write_json, write_text
from .generator import generate_and_select
from .planner import compile_image_prompt
from .preparation import prepare_paper_figure_contract
from .review import validate_review_coverage
from .templates import build_template_profiles, render_layout_blueprint, select_template


def run_paper_to_image(
    paper: str | Path,
    out: str | Path,
    preferences_path: str | Path | None = None,
    positive_references: list[str] | None = None,
    negative_references: list[str] | None = None,
    planner_mode: str = "vlm",
    planner_model: str | None = None,
    asset_mode: str = "image2",
    candidates: int = 3,
    aspect_ratio: str | None = None,
    language: str | None = None,
    image_model: str | None = None,
    image_retries: int = 2,
    review_mode: str = "heuristic",
    review_model: str | None = None,
    domain_profile: str = "auto",
    template: str = "auto",
    repair_rounds: int = 1,
    ocr_engine: str = "auto",
    ocr_lang: str = "en_ch",
    ocr_adapter=None,
    critic_adapter=None,
) -> dict:
    started = time.time()
    prepared = prepare_paper_figure_contract(
        paper=paper,
        out=out,
        deadline_seconds=600,
        planner_mode=planner_mode,
        planner_model=planner_model,
        ocr_engine=ocr_engine if ocr_engine in {"auto", "paddle", "easyocr", "off"} else "auto",
        ocr_lang=ocr_lang,
        preferences_path=preferences_path,
        positive_references=positive_references,
        negative_references=negative_references,
        aspect_ratio=aspect_ratio,
        language=language,
        domain_profile=domain_profile,
        ocr_adapter=ocr_adapter,
    )
    if not prepared.get("ok"):
        raise ValueError(f"Paper contract preparation failed: {prepared.get('errors') or prepared.get('planning_validation', {}).get('errors')}")
    root = prepared["root"]
    archived_paper = prepared["paper"]
    archived_positive = prepared["archived_positive"]
    archived_negative = prepared["archived_negative"]
    preferences = prepared["preferences"]
    parsed = prepared["parsed"]
    selected_domain = prepared["selected_domain"]
    paper_review = prepared["paper_review"]
    review_metadata = prepared["review_metadata"]
    plan = prepared["plan"]
    planner_metadata = prepared["planner_metadata"]
    planning_validation = prepared["planning_validation"]
    production_mode = asset_mode == "image2"
    if production_mode and not parsed.get("extraction_report", {}).get("scientific_scope_complete", True):
        raise RuntimeError("Production Image2 generation requires full-document scientific scope; sampled scanned-paper contracts are engineering-only")
    coverage = validate_review_coverage(paper_review, parsed, selected_domain, strict=production_mode)
    write_json(root / "review_coverage_report.json", coverage)
    if production_mode and review_metadata.get("mode") != "vlm":
        raise RuntimeError("Production Image2 generation requires successful VLM paper review")
    if not coverage["ok"]:
        raise ValueError(f"Paper review failed coverage validation: {coverage['errors']}")

    template_profiles = build_template_profiles(archived_positive, root / "template_profiles", mode=planner_mode, model=planner_model)
    selected_template = select_template(template_profiles, paper_review, requested=template, target_ratio=str(preferences.get("aspect_ratio") or "auto"))
    if str(preferences.get("aspect_ratio") or "auto") == "auto":
        ratio = float(selected_template.get("source_aspect_ratio") or selected_template.get("aspect_ratio") or 16 / 9)
        preferences["template_source_aspect_ratio"] = round(ratio, 6)
        preferences["aspect_ratio"] = "3:2" if ratio >= 1.25 else "2:3" if ratio <= 0.80 else "1:1"
        preferences["generation_ratio_policy"] = "nearest_native_image2_canvas; preserve_template_internal_geometry; no_semantic_crop"
        write_json(root / "preferences.json", preferences)
    write_json(root / "selected_template.json", {"summary": "Automatically or explicitly selected content-free architecture template.", **selected_template})
    blueprint_report = render_layout_blueprint(selected_template, root / "layout_blueprint.png", target_ratio=preferences["aspect_ratio"])
    write_json(root / "layout_blueprint.json", blueprint_report)

    plan["style_plan"]["selected_template_id"] = selected_template.get("profile_id")
    plan["style_plan"]["template_style"] = selected_template.get("style", {})
    plan["style_plan"]["template_palette"] = selected_template.get("palette", [])
    write_json(root / "style_plan.json", plan["style_plan"])
    write_json(root / "planning_validation_report.json", planning_validation)
    if not planning_validation["ok"]:
        raise ValueError(f"Paper-to-image planning failed scientific grounding validation: {planning_validation['errors']}")

    final_prompt = compile_image_prompt(plan, preferences, candidate_variant=1, selected_template=selected_template)
    write_text(root / "image_prompt.txt", final_prompt)
    generation_parameters = {
        "summary": "Image generation parameters.",
        "asset_mode": asset_mode,
        "image_model": image_model,
        "aspect_ratio": preferences["aspect_ratio"],
        "language": preferences["language"],
        "candidate_count": max(1, min(4, int(candidates))),
        "image_retries": max(0, min(5, int(image_retries))),
        "review_mode": review_mode,
        "review_model": review_model,
        "domain_profile": selected_domain["id"],
        "template": selected_template["template_id"],
        "repair_rounds": max(0, min(1, int(repair_rounds))),
        "ocr_engine": ocr_engine,
        "ocr_lang": ocr_lang,
    }
    write_json(root / "generation_parameters.json", generation_parameters)

    generation = generate_and_select(
        plan,
        preferences,
        selected_template,
        root / "layout_blueprint.png",
        root,
        asset_mode=asset_mode,
        candidates=candidates,
        image_model=image_model,
        image_retries=image_retries,
        review_mode=review_mode,
        review_model=review_model,
        repair_rounds=repair_rounds,
        ocr_engine=ocr_engine,
        ocr_lang=ocr_lang,
        ocr_adapter=ocr_adapter,
        critic_adapter=critic_adapter,
    )
    elapsed = round(time.time() - started, 3)
    run_summary: dict[str, Any] = {
        "summary": "Paper-to-image workflow completed without PPTX generation.",
        "ok": True,
        "out_dir": str(root),
        "paper": archived_paper,
        "planner_mode": planner_metadata["mode"],
        "planner_model": planner_metadata.get("model"),
        "planner_warning": planner_metadata.get("warning"),
        "paper_review_mode": review_metadata.get("mode"),
        "domain_profile": selected_domain["id"],
        "template_id": selected_template["template_id"],
        "asset_mode": asset_mode,
        "review_mode": review_mode,
        "candidate_count": generation["successful_candidates"],
        "selected_image": generation.get("selected_image"),
        "engineering_preview": generation.get("engineering_preview"),
        "selected_candidate_id": generation["selected_candidate_id"],
        "selected_passed_all_checks": generation["selected_passed_all_checks"],
        "elapsed_seconds": elapsed,
        "pptx_generated": False,
        "artifacts": [
            "input_manifest.json",
            "preferences.json",
            "evidence_map.json",
            "document_index.json",
            "paper_review.json",
            "review_coverage_report.json",
            "domain_profile.json",
            "template_profiles/",
            "selected_template.json",
            "layout_blueprint.png",
            "paper_summary.json",
            "figure_specification.json",
            "design_plan.json",
            "layout_intent.json",
            "visual_metaphors.json",
            "style_plan.json",
            "planning_validation_report.json",
            "image_prompt.txt",
            "generation_parameters.json",
            "image2_request_manifest.json",
            "candidate_review.json",
            "ocr_review.json",
            "template_alignment_report.json",
            "scientific_critic_report.json",
            "aesthetic_critic_report.json",
            "selected_image.png" if generation.get("selected_image") else "engineering_preview.png",
        ],
    }
    write_json(root / "run_summary.json", run_summary)
    return run_summary
