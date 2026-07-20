from __future__ import annotations

from pathlib import Path
from typing import Any

from .editable_rebuild import rebuild_editable
from .paper_to_image import run_paper_to_image
from .rebuild_vlm_adapters import build_rebuild_vlm_adapters
from .semantic_contract import load_paper_semantic_contract
from .utils import ensure_dir, write_json


def run_paper_to_editable(
    paper: str | Path,
    out: str | Path,
    preferences_path: str | Path | None = None,
    positive_references: list[str] | None = None,
    negative_references: list[str] | None = None,
    planner_mode: str = "vlm",
    planner_model: str | None = None,
    image_asset_mode: str = "image2",
    image_candidates: int = 3,
    aspect_ratio: str | None = None,
    language: str | None = None,
    image_model: str | None = None,
    image_retries: int = 2,
    review_mode: str = "vlm",
    review_model: str | None = None,
    domain_profile: str = "auto",
    template: str = "auto",
    repair_rounds: int = 1,
    rebuild_asset_mode: str = "api",
    rebuild_asset_policy: str = "smart-api",
    layout_mode: str = "hybrid",
    control_mode: str = "hybrid",
    text_mode: str = "ocr",
    design_plan_mode: str = "vlm",
    export_preview: bool = True,
    allow_engineering_preview: bool = False,
    ocr_engine: str = "auto",
    ocr_lang: str = "en_ch",
    critic_adapter=None,
) -> dict[str, Any]:
    root = ensure_dir(out).resolve()
    image_dir = root / "paper_to_image"
    editable_dir = root / "editable"
    image_result = run_paper_to_image(
        paper=paper,
        out=image_dir,
        preferences_path=preferences_path,
        positive_references=positive_references,
        negative_references=negative_references,
        planner_mode=planner_mode,
        planner_model=planner_model,
        asset_mode=image_asset_mode,
        candidates=image_candidates,
        aspect_ratio=aspect_ratio,
        language=language,
        image_model=image_model,
        image_retries=image_retries,
        review_mode=review_mode,
        review_model=review_model,
        domain_profile=domain_profile,
        template=template,
        repair_rounds=repair_rounds,
        ocr_engine=ocr_engine,
        ocr_lang=ocr_lang,
        critic_adapter=critic_adapter,
    )
    reference = image_result.get("selected_image")
    reference_status = "production_selected_image"
    if not reference and allow_engineering_preview:
        reference = image_result.get("engineering_preview")
        reference_status = "engineering_preview_explicitly_allowed"
    if not reference:
        blocked = {
            "summary": "Paper-to-editable delivery blocked before rebuild because no production-approved image exists.",
            "ok": False,
            "delivery_blocked": True,
            "out_dir": str(root),
            "paper_to_image": image_result,
            "policy": "failed image candidates are never promoted to production editable output",
        }
        write_json(root / "paper_to_editable_result.json", blocked)
        return blocked

    contract = load_paper_semantic_contract(image_dir)
    adapters = build_rebuild_vlm_adapters(editable_dir)
    rebuild_ocr_engine = ocr_engine if ocr_engine in {"paddle", "easyocr", "off"} else "paddle"
    editable_result = rebuild_editable(
        reference=reference,
        out=editable_dir,
        asset_mode=rebuild_asset_mode,
        asset_policy=rebuild_asset_policy,
        text_mode=text_mode,
        layout_mode=layout_mode,
        control_mode=control_mode,
        export_preview=export_preview,
        ocr_engine=rebuild_ocr_engine,
        ocr_lang=ocr_lang,
        vlm_layout_adapter=adapters["layout"] if layout_mode in {"vlm", "hybrid"} else None,
        control_adapter=adapters["control"] if control_mode in {"vlm", "hybrid"} else None,
        semantic_adapter=adapters["semantic"] if layout_mode in {"vlm", "hybrid"} or control_mode in {"vlm", "hybrid"} else None,
        design_plan_mode=design_plan_mode,
        design_adapter=adapters["design"] if design_plan_mode == "vlm" else None,
        semantic_contract=contract,
    )
    result = {
        "summary": "Paper-to-editable workflow completed with paper-grounded semantic bindings.",
        "ok": bool(editable_result.get("ok")),
        "delivery_blocked": False,
        "out_dir": str(root),
        "reference_status": reference_status,
        "reference_image": str(reference),
        "paper_to_image_dir": str(image_dir),
        "editable_dir": str(editable_dir),
        "pptx": editable_result.get("pptx"),
        "preview": editable_result.get("preview"),
        "semantic_binding_status": editable_result.get("semantic_binding_status"),
        "paper_to_image": image_result,
        "editable_rebuild": editable_result,
    }
    write_json(root / "paper_to_editable_result.json", result)
    return result
