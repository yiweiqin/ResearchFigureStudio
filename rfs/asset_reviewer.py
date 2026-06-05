from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from .utils import write_json


def _extract_json(text: str) -> dict:
    cleaned = text.strip().replace("```json", "```")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _call_vlm_json(prompt: str, image_paths: list[str | Path], model: str | None = None) -> dict:
    api_base = os.getenv("API_BASE", "").rstrip("/")
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
    model_name = model or os.getenv("RFS_CRITIC_MODEL") or os.getenv("MODEL_VLM") or "gemini-3-pro-preview-thinking"
    if not api_base or not api_key:
        raise RuntimeError("VLM review requires API_BASE and API_KEY/GEMINI_API_KEY environment variables")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in image_paths:
        p = Path(path)
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
    }
    response = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=180,
    )
    response.raise_for_status()
    result_text = response.json()["choices"][0]["message"]["content"]
    return _extract_json(result_text)


def review_assets(out_dir: str | Path, mode: str = "heuristic", model: str | None = None) -> dict:
    out = Path(out_dir)
    contact_sheet = out / "asset_contact_sheet.png"
    report_path = out / "asset_quality_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"assets": []}
    complexity_path = out / "asset_complexity_report.json"
    complexity_report = json.loads(complexity_path.read_text(encoding="utf-8")) if complexity_path.exists() else {"assets": []}
    complexity_by_slot = {
        str(item.get("slot_id")): item
        for item in complexity_report.get("assets", [])
        if isinstance(item, dict) and item.get("slot_id")
    }

    if mode == "off":
        review = {"summary": "Asset visual review skipped by configuration.", "mode": "off", "issues": []}
    elif mode == "heuristic":
        issues = []
        for item in report.get("assets", []):
            tags = list(item.get("issue_tags", []))
            if float(item.get("content_fill_percent", 0)) < 85:
                tags.append("too_sparse")
            if float(item.get("empty_margin_percent", 100)) > 10:
                tags.append("large_blank_canvas")
            complexity = complexity_by_slot.get(str(item.get("slot_id")), {})
            if complexity.get("simple_icon_risk"):
                tags.append("too_simple")
            complexity_tags = complexity.get("complexity_issue_tags", []) if isinstance(complexity.get("complexity_issue_tags"), list) else []
            for tag in complexity_tags:
                if tag in {"too_simple", "generic_icon", "reference_crop_ignored", "single_object_on_blank_background", "style_drift"}:
                    tags.append(tag)
            if tags:
                issues.append({"asset_id": item.get("asset_id"), "slot_id": item.get("slot_id"), "issue_tags": sorted(set(tags)), "severity": "major"})
        review = {
            "summary": "Heuristic asset visual review based on fill, margin, ratio, and complexity metrics.",
            "mode": "heuristic",
            "contact_sheet": str(contact_sheet) if contact_sheet.exists() else None,
            "issues": issues,
            "status": "pass" if not issues else "needs_regeneration",
        }
    elif mode == "vlm":
        assets_brief = [
            {
                "asset_id": item.get("asset_id"),
                "slot_id": item.get("slot_id"),
                "content_fill_percent": item.get("content_fill_percent"),
                "empty_margin_percent": item.get("empty_margin_percent"),
                "detail_score": complexity_by_slot.get(str(item.get("slot_id")), {}).get("detail_score"),
                "simple_icon_risk": complexity_by_slot.get(str(item.get("slot_id")), {}).get("simple_icon_risk"),
                "complexity_issue_tags": complexity_by_slot.get(str(item.get("slot_id")), {}).get("complexity_issue_tags"),
            }
            for item in report.get("assets", [])
        ]
        prompt = f"""
You are an asset-quality critic for image-rich scientific framework figures.
Inspect the contact sheet of selected slot image blocks.
Only output JSON. Do not output prose or markdown.

Check for these issues:
- too_simple: looks like a generic sparse icon instead of a rich research visual block
- generic_icon: looks like a standalone pictogram rather than a reference-guided mini scientific scene/card
- reference_crop_ignored: does not visually resemble the local reference crop object
- single_object_on_blank_background: one object floats on a plain canvas
- style_drift: local color/style does not match the reference figure
- too_sparse: too much empty canvas or subject too small
- bad_text: readable wrong text, fake formulas, fake axes, fake metrics, or misspelled scientific labels
- cut_off: subject or card is visibly clipped
- style_drift: style inconsistent across blocks
- low_resolution: blur or artifacts

Return schema:
{{
  "summary": "...",
  "mode": "vlm",
  "status": "pass|needs_regeneration",
  "issues": [{{"asset_id":"...","slot_id":"...","issue_tags":["too_simple"],"severity":"minor|major","reason":"..."}}],
  "global_style_notes": ["..."]
}}

Asset list:
{json.dumps(assets_brief, ensure_ascii=False)}
""".strip()
        review = _call_vlm_json(prompt, [contact_sheet], model=model)
        review.setdefault("summary", "VLM asset visual review for selected slot blocks.")
        review.setdefault("mode", "vlm")
    else:
        raise ValueError(f"Unsupported asset review mode: {mode}")

    write_json(out / "asset_visual_review.json", review)
    return review
