from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from .utils import write_json, write_text


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _title_guess(text: str) -> str:
    lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
    skip = ("proceedings", "november", "abstract", "introduction", "copyright", "©")
    for index, line in enumerate(lines[:80]):
        low = line.lower()
        if low.startswith(skip) or "association for computational linguistics" in low:
            continue
        if 20 <= len(line) <= 140:
            nxt = lines[index + 1] if index + 1 < len(lines) else ""
            if 8 <= len(nxt) <= 90 and not re.search(r"\d", nxt[:8]) and not nxt.lower().startswith(("abstract", "author")):
                merged = f"{line} {nxt}"
                if len(merged) <= 180:
                    return merged
            return line
    return "Untitled AI/ML research figure task"


def _section_snippets(text: str, limit: int = 60000) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text)
    if len(cleaned) <= limit:
        return cleaned
    head = cleaned[: int(limit * 0.62)]
    method_hits = []
    for pattern in [r"(?is)\n3\s+.*?(?=\n4\s+|\n5\s+|\n6\s+|$)", r"(?is)\n4\s+.*?(?=\n5\s+|\n6\s+|$)", r"(?is)\n5\s+.*?(?=\n6\s+|$)"]:
        match = re.search(pattern, cleaned)
        if match:
            method_hits.append(match.group(0)[: int(limit * 0.18)])
    tail = cleaned[-int(limit * 0.15) :]
    return "\n\n".join([head] + method_hits + [tail])[:limit]


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


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return (slug[:52] or fallback).strip("_")


def _extract_variables(text: str) -> list[str]:
    patterns = [
        r"(?:Delta|∆)\s*W\s*=\s*[^,\n]+",
        r"W\s*[∈in]+\s*R[^\s,;]+",
        r"A\s*[∈in]+\s*R[^\s,;]+",
        r"B(?:_[A-Za-z0-9]+)?\s*[∈in]+\s*R[^\s,;]+",
        r"[A-Z][A-Za-z0-9_]*\s*=\s*\([^\)]+\)",
        r"[A-Z][A-Za-z0-9_]*\s*=\s*\[[^\]]+\]",
        r"IFT\([^\)]+\)",
        r"LoRA",
        r"FoRA-UA",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            value = _clean_line(match if isinstance(match, str) else match[0])
            if value and value not in found and len(value) <= 120:
                found.append(value)
    return found[:18]


def _extract_headings(text: str) -> list[str]:
    headings = []
    for match in re.findall(r"(?m)^\s*(?:\d+(?:\.\d+)*\s+)?([A-Z][A-Za-z0-9 ,:/\-()]{8,90})\s*$", text[:50000]):
        item = _clean_line(match)
        low = item.lower()
        if low in {"abstract", "introduction", "references", "appendix"}:
            continue
        if any(token in low for token in ["proceedings", "conference", "association for computational linguistics"]):
            continue
        if item not in headings:
            headings.append(item)
    return headings[:12]


def _fallback_brief(text: str) -> dict:
    title = _title_guess(text)
    headings = _extract_headings(text)
    modules = headings[:7] or [
        "Research Problem",
        "Core Method",
        "Parameter or Data Flow",
        "Training Procedure",
        "Evaluation Setup",
        "Results Summary",
    ]
    variables = _extract_variables(text)

    keyword_candidates = []
    for pattern in [
        r"\b[A-Z][A-Za-z0-9\-]{2,}(?:-[A-Z][A-Za-z0-9]+)+\b",
        r"\b(?:LoRA|Adapter|FourierFT|FoRA-UA|VeRA|DoRA|PEFT|IFT|FFT|GLUE|LLaMA|RoBERTa|GPT-2|ViT)\b",
        r"\b(?:frozen|trainable|sparse|matrix|projection|rank|split|intermediate|frequency|benchmark|ablation)\b",
    ]:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            item = _clean_line(match)
            if item.lower() not in {x.lower() for x in keyword_candidates}:
                keyword_candidates.append(item)
    concepts = []
    for module in modules:
        concepts.append(module)
    for item in keyword_candidates:
        if item not in concepts:
            concepts.append(item)
    for item in variables:
        if item not in concepts:
            concepts.append(item)
    while len(concepts) < 32:
        concepts.append(f"{modules[len(concepts) % len(modules)]} visual unit")

    return {
        "summary": "Paper-grounded brief produced by heuristic fallback.",
        "planner": "heuristic",
        "title_guess": title,
        "figure_kind": "paper_driven_generic",
        "figure_goal": "Paper-grounded AI/ML method framework figure based on extracted modules and concepts.",
        "modules": modules,
        "concepts": concepts[:50],
        "variables": variables,
        "slot_suggestions": _slots_from_modules(modules, concepts[:50], 36),
        "warnings": ["LLM paper planner was unavailable or disabled; used heuristic extraction."],
    }


def _slots_from_modules(modules: list[str], concepts: list[str], target_count: int) -> list[dict]:
    modules = modules or ["Research Problem", "Core Method", "Evaluation"]
    concepts = concepts or modules
    target_count = max(25, min(50, int(target_count)))
    slots = []
    for index in range(target_count):
        panel = modules[index % len(modules)]
        concept = concepts[index % len(concepts)]
        composition = "full_bleed_card"
        low = concept.lower()
        if any(word in low for word in ["dataset", "example", "input", "output", "task", "image", "video"]):
            composition = "scene_thumbnail"
        elif any(word in low for word in ["score", "metric", "rank", "budget", "parameter", "label", "icon"]):
            composition = "full_frame_icon"
        slots.append({
            "id": f"{_slug(concept, f'slot_{index+1:02d}')}_{index+1:02d}",
            "macro_panel": panel,
            "paper_concept": concept,
            "composition_type": composition,
            "visual_metaphor": _heuristic_visual_metaphor(concept, panel),
            "must_show": _heuristic_must_show(concept),
            "avoid_showing": ["generic sci-fi dashboard", "unrelated robot or brain", "fake formulas", "fake numeric chart text"],
        })
    return slots


def _heuristic_visual_metaphor(concept: str, panel: str) -> str:
    low = f"{concept} {panel}".lower()
    if "sparse" in low or "nonzero" in low:
        return "matrix grid with many pale empty cells and a few bright highlighted trainable cells"
    if "empty" in low or "zero" in low:
        return "mostly empty matrix grid with faint zero cells and reserved blank positions"
    if "frozen" in low or "pre-trained" in low or "pretrained" in low:
        return "large locked weight matrix slab with cold frozen shading and no trainable highlights"
    if "lora" in low:
        return "two narrow low-rank matrix blocks connected as a small adapter update beside a larger frozen weight matrix"
    if "ift" in low or "fourier" in low or "frequency" in low:
        return "frequency-domain grid transforming into a smoother spatial-domain matrix through wave-like arcs"
    if "split" in low or "submat" in low:
        return "one matrix separated into several smaller aligned submatrices with clean cut lines"
    if "concat" in low:
        return "several transformed matrix blocks stacked vertically into one taller matrix"
    if "adaptor" in low or "adapter" in low:
        return "frozen shared projection block receiving concatenated matrix features and outputting a compact update"
    if "rank" in low or "budget" in low or "parameter" in low:
        return "parameter budget gauge comparing many muted frozen cells with a tiny number of highlighted trainable cells"
    if "evaluation" in low or "benchmark" in low or "glue" in low:
        return "benchmark panel with multiple task tiles and abstract performance bars without readable numbers"
    return f"paper-specific visual card for {concept}: show the mechanism in {panel} using concrete matrices, arrows, and scientific objects"


def _heuristic_must_show(concept: str) -> list[str]:
    low = concept.lower()
    items: list[str] = []
    if any(word in low for word in ["matrix", "lora", "sparse", "fourier", "ift", "submat", "projection", "adaptor", "adapter"]):
        items.extend(["matrix-like blocks", "clear input-output relation", "distinct trainable vs frozen regions"])
    if "sparse" in low or "nonzero" in low:
        items.extend(["few highlighted nonzero cells", "many pale empty cells"])
    if "split" in low or "submat" in low:
        items.extend(["one-to-many split", "multiple smaller blocks"])
    if "concat" in low:
        items.extend(["vertical stacking", "merged larger block"])
    if "budget" in low or "parameter" in low:
        items.extend(["small highlighted trainable budget", "large muted frozen background"])
    if not items:
        items = ["concrete scientific object", "visible structure", "paper-specific process cue"]
    return list(dict.fromkeys(items))[:5]


def _call_llm_planner(text: str, target_slots: int = 36) -> dict:
    api_base = os.getenv("API_BASE", "").rstrip("/")
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
    model = os.getenv("RFS_PAPER_PLANNER_MODEL") or os.getenv("MODEL_PLANNER") or os.getenv("MODEL_VLM") or "gemini-3-pro-preview-thinking"
    if not api_base or not api_key:
        raise RuntimeError("Paper planner requires API_BASE and API_KEY/GEMINI_API_KEY")

    excerpt = _section_snippets(text)
    prompt = f"""
You are a paper-to-figure planner for AI/ML/NLP papers.
Return only JSON. Do not use a fixed paper template. Do not invent generic encoder/retriever/decoder modules unless the paper actually uses those terms.

Goal: create a paper-grounded plan for a complex, image-rich, editable PowerPoint system/method figure.
The figure will later be built from 25-50 small image slots plus editable PPT labels/arrows/formulas.

Return schema:
{{
  "summary": "Paper-grounded figure brief.",
  "planner": "llm",
  "title_guess": "...",
  "figure_kind": "method|architecture|dataset|benchmark|analysis|system|paper_driven_generic",
  "figure_goal": "...",
  "modules": ["5-8 ordered macro panels using paper terminology"],
  "concepts": ["30-60 paper-specific concepts, variables, operations, findings, evaluations"],
  "variables": ["important formulas or symbols exactly as text when available"],
  "slot_suggestions": [
    {{
      "id": "stable_snake_case_id",
      "macro_panel": "one of modules",
      "paper_concept": "paper-specific visual unit",
      "composition_type": "full_frame_icon|full_bleed_card|scene_thumbnail|symbol_cutout",
      "visual_metaphor": "concrete thing to draw, e.g. sparse matrix grid with highlighted nonzero cells",
      "must_show": ["2-5 visible objects or relations that make this slot paper-specific"],
      "avoid_showing": ["generic sci-fi dashboard", "unrelated robot", "fake formulas", "fake numeric chart text"]
    }}
  ],
  "warnings": ["scientific ambiguities or missing information"]
}}

Rules:
- slot_suggestions must contain at least {target_slots} entries.
- Use the paper's exact method names, variables, findings, datasets, benchmarks, and operations.
- Every slot must include a concrete visual_metaphor and must_show list. Do not leave the image model to infer the visual from only a noun phrase such as "LoRA" or "parameters".
- Critical text/formulas will be added later in PPT, so slots should describe visual units, not final labels.
- Avoid any concepts from other papers.

Paper text:
{excerpt}
""".strip()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }
    response = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=240,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _normalize_brief(raw: dict, text: str, target_slots: int = 36) -> dict:
    fallback = _fallback_brief(text)
    modules = [str(item).strip() for item in raw.get("modules", []) if str(item).strip()]
    concepts = [str(item).strip() for item in raw.get("concepts", []) if str(item).strip()]
    variables = [str(item).strip() for item in raw.get("variables", []) if str(item).strip()]
    if len(modules) < 3:
        modules = fallback["modules"]
    modules = modules[:8]
    if len(concepts) < 12:
        concepts = fallback["concepts"]
    merged_variables = []
    for item in variables + _extract_variables(text):
        if item and item not in merged_variables:
            merged_variables.append(item)

    raw_slots = raw.get("slot_suggestions", [])
    slots = []
    if isinstance(raw_slots, list):
        for index, item in enumerate(raw_slots):
            if not isinstance(item, dict):
                continue
            panel = str(item.get("macro_panel") or modules[index % len(modules)]).strip()
            if panel not in modules:
                panel = modules[index % len(modules)]
            concept = str(item.get("paper_concept") or (concepts[index % len(concepts)])).strip()
            ctype = str(item.get("composition_type") or "full_bleed_card").strip()
            if ctype not in {"full_frame_icon", "full_bleed_card", "scene_thumbnail", "symbol_cutout"}:
                ctype = "full_bleed_card"
            slot_id = _slug(str(item.get("id") or concept), f"slot_{index+1:02d}")
            visual_metaphor = str(item.get("visual_metaphor") or _heuristic_visual_metaphor(concept, panel)).strip()
            must_show = item.get("must_show") if isinstance(item.get("must_show"), list) else _heuristic_must_show(concept)
            avoid_showing = item.get("avoid_showing") if isinstance(item.get("avoid_showing"), list) else [
                "generic sci-fi dashboard",
                "unrelated robot or brain",
                "fake formulas",
                "fake numeric chart text",
            ]
            slots.append({
                "id": f"{slot_id}_{index+1:02d}",
                "macro_panel": panel,
                "paper_concept": concept,
                "composition_type": ctype,
                "visual_metaphor": visual_metaphor,
                "must_show": [str(x) for x in must_show[:5]],
                "avoid_showing": [str(x) for x in avoid_showing[:5]],
            })
    if len(slots) < target_slots:
        slots = _slots_from_modules(modules, concepts, target_slots)
    else:
        slots = slots[: max(25, min(50, target_slots))]

    return {
        "summary": "Paper-grounded brief extracted before figure planning.",
        "planner": raw.get("planner") or "llm",
        "title_guess": str(raw.get("title_guess") or fallback["title_guess"]),
        "figure_kind": str(raw.get("figure_kind") or "paper_driven_generic"),
        "figure_goal": str(raw.get("figure_goal") or fallback["figure_goal"]),
        "modules": modules,
        "concepts": concepts[:60],
        "variables": merged_variables[:24],
        "slot_suggestions": slots,
        "warnings": [str(item) for item in raw.get("warnings", []) if str(item).strip()],
    }


def analyze_paper(loaded: dict, out_dir: str | Path) -> dict:
    text = loaded.get("text", "")
    target_slots = int(os.getenv("RFS_TARGET_SLOTS", "36"))
    mode = os.getenv("RFS_PAPER_PLANNER_MODE", "llm").lower()

    if mode == "off" or mode == "heuristic":
        brief = _normalize_brief(_fallback_brief(text), text, target_slots=target_slots)
        brief["planner"] = "heuristic"
    else:
        try:
            brief = _normalize_brief(_call_llm_planner(text, target_slots=target_slots), text, target_slots=target_slots)
        except Exception as exc:
            brief = _normalize_brief(_fallback_brief(text), text, target_slots=target_slots)
            brief["planner"] = "heuristic_after_llm_failure"
            brief.setdefault("warnings", []).append(f"LLM planner failed: {exc}")

    brief.update({
        "source_path": loaded.get("path"),
        "source_loader": loaded.get("loader"),
        "char_count": loaded.get("char_count", 0),
    })

    out_path = Path(out_dir)
    write_json(out_path / "paper_brief.json", brief)
    md = [
        "# Summary",
        "Paper-grounded figure brief extracted before layout and image generation.",
        "",
        "## Source",
        f"- Path: `{brief['source_path']}`",
        f"- Loader: `{brief['source_loader']}`",
        f"- Planner: {brief['planner']}",
        f"- Title guess: {brief['title_guess']}",
        "",
        "## Figure Goal",
        brief["figure_goal"],
        "",
        "## Paper Modules",
    ]
    md.extend(f"- {item}" for item in brief["modules"])
    md.extend(["", "## Paper Concepts"])
    md.extend(f"- {item}" for item in brief["concepts"])
    if brief["variables"]:
        md.extend(["", "## Variables"])
        md.extend(f"- `{item}`" for item in brief["variables"])
    if brief["warnings"]:
        md.extend(["", "## Warnings"])
        md.extend(f"- {item}" for item in brief["warnings"])
    write_text(out_path / "paper_brief.md", "\n".join(md) + "\n")
    return brief
