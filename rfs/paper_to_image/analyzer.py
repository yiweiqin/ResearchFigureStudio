from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable


MOJIBAKE_MARKERS = ("\ufffd", "Ã", "Â", "â€", "锟", "鈥", "銆", "鏅")
SECTION_ALIASES = {
    "abstract": ("abstract", "摘要", "概要", "초록"),
    "introduction": ("introduction", "background", "引言", "介绍", "背景", "はじめに", "序論", "서론", "배경"),
    "method": ("method", "methods", "methodology", "approach", "architecture", "system overview", "framework", "方法", "方法论", "架构", "系统概述", "框架", "手法", "方法論", "アーキテクチャ", "방법", "방법론", "아키텍처"),
    "experiments": ("experiment", "experiments", "evaluation", "results", "实验", "评估", "结果", "実験", "評価", "結果", "실험", "평가", "결과"),
    "conclusion": ("conclusion", "conclusions", "discussion", "结论", "讨论", "总结", "結論", "考察", "まとめ", "결론", "논의", "요약"),
}

OCR_PROTECTED_WORDS = {
    "acknowledgements", "architecture", "autoregressive", "bidirectional", "classification", "configuration",
    "convolutional", "deterministic", "differentiable", "downstream", "embedding", "embeddings", "evaluation",
    "experimental", "experiments", "finetuning", "implementation", "information", "initialization", "introduction",
    "methodology", "multiframe", "multimodal", "optimization", "performance", "positional", "pretraining",
    "probabilities", "representation", "representations", "retrieval", "scientific", "segmentation", "transformer",
    "visualization",
}
OCR_SPLIT_ANCHORS = OCR_PROTECTED_WORDS | {
    "and", "decoder", "encoder", "evidence", "for", "from", "generation", "into", "method", "model", "of",
    "output", "retriever", "the", "to", "with",
}


def _clean(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).replace("\u00ad", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    previous = None
    while previous != value:
        previous = value
        value = re.sub(r"\b([A-Z])\s+([A-Z]{2,})\b", r"\1\2", value)
    value = re.sub(r"\bANIMAGE\b", "AN IMAGE", value)
    value = re.sub(r"\(\s*([A-Z])\s+([A-Z])\s+([A-Z])\s*\)", r"(\1\2\3)", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _repair_ocr_spacing(text: str, splitter: Callable[[str], list[str]] | None = None) -> tuple[str, int]:
    value = _clean(text)
    repairs = 0
    value, count = re.subn(r"\b(figure|fig\.|table)(?=\d)", r"\1 ", value, flags=re.IGNORECASE)
    repairs += count
    section_terms = "abstract|introduction|background|method|methods|approach|experiments|results|conclusion|discussion|references|appendix"
    value, count = re.subn(rf"(?<!\w)(\d+(?:\.\d+)*)(?=(?:{section_terms})\b)", r"\1 ", value, flags=re.IGNORECASE)
    repairs += count
    cjk_section_terms = "\u7cfb\u7edf\u6982\u8ff0|\u65b9\u6cd5\u8bba|\u53c2\u8003\u6587\u732e|\u5b9e\u9a8c|\u7ed3\u8bba|\u8ba8\u8bba|\u5f15\u8a00|\u80cc\u666f|\u65b9\u6cd5|\u67b6\u6784|\u6846\u67b6|\u8bc4\u4f30|\u7ed3\u679c|\u9644\u5f55"
    value, count = re.subn(rf"^(\d+(?:\.\d+)*)(?=(?:{cjk_section_terms})(?:\s|$))", r"\1 ", value)
    repairs += count
    value, count = re.subn(r"(?<=[,:;])(?=[A-Z])", " ", value)
    repairs += count
    if splitter is None:
        try:
            import wordninja

            splitter = wordninja.split
        except Exception:
            splitter = None
    if splitter is None:
        return value, repairs

    def split_token(match: re.Match[str]) -> str:
        nonlocal repairs
        token = match.group(0)
        normalized = token.casefold()
        if normalized in OCR_PROTECTED_WORDS or token.isupper() or (token[1:] != token[1:].lower() and token[1:] != token[1:].upper()):
            return token
        pieces = [str(piece) for piece in splitter(token) if str(piece)]
        lowered = [piece.casefold() for piece in pieces]
        if len(pieces) < 2 or any(len(piece) < 2 for piece in pieces) or not any(piece in OCR_SPLIT_ANCHORS for piece in lowered):
            return token
        repairs += len(pieces) - 1
        return " ".join(pieces)

    value = re.sub(r"[A-Za-z]{8,160}", split_token, value)
    return _clean(value), repairs


def _normalized_compare_text(text: str) -> str:
    return "".join(char for char in _clean(text).casefold() if char.isalnum())


def _lexical_units(text: str) -> list[str]:
    clean = _clean(text).casefold()
    units = [f"latin:{value}" for value in re.findall(r"[a-z]{3,}", clean)]
    cjk = "".join(re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", clean))
    if len(cjk) == 1:
        units.append(f"cjk:{cjk}")
    else:
        units.extend(f"cjk:{cjk[index:index + 2]}" for index in range(len(cjk) - 1))
    return units


def _cjk_character_count(text: str) -> int:
    return sum(
        "\u3400" <= char <= "\u9fff"
        or "\u3040" <= char <= "\u30ff"
        or "\uac00" <= char <= "\ud7af"
        for char in str(text or "")
    )


def _token_overlap_agreement(left: str, right: str) -> float | None:
    left_tokens = _lexical_units(left)
    right_tokens = _lexical_units(right)
    if not left_tokens or not right_tokens:
        return None
    overlap = sum((Counter(left_tokens) & Counter(right_tokens)).values())
    return round(overlap / max(1, len(left_tokens)), 4)


def _replacement_rate(text: str) -> float:
    value = str(text or "")
    return round(value.count("\ufffd") / max(1, len(value)), 6)


def _mojibake_rate(text: str) -> float:
    value = str(text or "")
    return round(sum(value.count(marker) for marker in MOJIBAKE_MARKERS) / max(1, len(value)), 6)


def _looks_like_typographic_heading(text: str) -> bool:
    value = _clean(text)
    words = re.findall(r"[A-Za-z][A-Za-z0-9+&/-]*", value)
    first_alpha = next((char for char in value if char.isalpha()), "")
    first_char = value[0] if value else ""
    if not 2 <= len(value) <= 100 or not 1 <= len(words) <= 10:
        return False
    if not first_char.isalpha() or (first_char.isascii() and not re.search(r"[a-z]", value)):
        return False
    if re.match(r"^(?:figure|fig\.|table)\b", value, re.IGNORECASE) or re.search(r"[=<>]{1,2}|\bdoi\b|https?://", value, re.IGNORECASE):
        return False
    if value.endswith(":") and len(words) <= 2:
        return False
    if value.endswith((",", ";", "?", "!")) or (value.endswith(".") and len(words) > 5):
        return False
    if first_alpha and first_alpha.lower() != first_alpha.upper() and not first_alpha.isupper():
        return False
    return True


def _block_kind(text: str, width_ratio: float = 0.0) -> str:
    value = _clean(text)
    if re.match(r"^(figure|fig\.|table|图|圖|表)\s*[a-z0-9一二三四五六七八九十]+", value, re.IGNORECASE):
        return "caption" if value.casefold().startswith(("figure", "fig.", "图", "圖")) else "table"
    section_aliases = tuple(alias.casefold() for aliases in SECTION_ALIASES.values() for alias in aliases)
    if len(value) <= 100 and any(value.casefold() == alias or value.casefold().startswith((f"{alias} ", f"{alias}:", f"{alias}：")) for alias in section_aliases):
        return "heading"
    if re.match(r"^(abstract|\d+(?:\.\d+)*\s+|[ivx]+[.)]\s+)(.{2,100})$", value, re.IGNORECASE) and len(value) <= 140:
        return "heading"
    if len(value) <= 180 and width_ratio >= 0.55 and not value.endswith((".", ",", ";")):
        return "title"
    if re.search(r"(?:[A-Za-z][A-Za-z0-9_{}^\-]*\s*=\s*[^=\n]{3,}|∑|∫|≤|≥|≈)", value):
        return "formula"
    return "paragraph"


def _column_groups(items: list[dict[str, Any]], page_width: float, max_columns: int = 3) -> list[list[dict[str, Any]]]:
    if len(items) < 4:
        return [items]
    positioned = sorted(items, key=lambda item: float(item["bbox"][0]))
    gaps = [
        (float(positioned[index + 1]["bbox"][0]) - float(positioned[index]["bbox"][0]), index)
        for index in range(len(positioned) - 1)
    ]
    qualified_gaps = [(gap, index) for gap, index in sorted(gaps, reverse=True) if gap >= page_width * 0.12]
    if not qualified_gaps:
        return [items]

    def median(values: list[float]) -> float:
        ordered = sorted(values)
        middle = len(ordered) // 2
        return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0

    def validated_groups(split_count: int) -> list[list[dict[str, Any]]] | None:
        split_indexes = sorted(index for _, index in qualified_gaps[:split_count])
        groups: list[list[dict[str, Any]]] = []
        start = 0
        for split in split_indexes:
            groups.append(positioned[start:split + 1])
            start = split + 1
        groups.append(positioned[start:])
        if len(groups) > max_columns or any(len(group) < 2 for group in groups):
            return None
        ordered_groups = sorted(groups, key=lambda group: median([float(item["bbox"][0]) for item in group]))
        minimum_vertical_span = page_width * 0.12
        minimum_text = 40
        for group in ordered_groups:
            vertical_span = max(float(item["bbox"][3]) for item in group) - min(float(item["bbox"][1]) for item in group)
            text_count = sum(len(_normalized_compare_text(str(item.get("text") or ""))) for item in group)
            if vertical_span < minimum_vertical_span or text_count < minimum_text:
                return None
        for left, right in zip(ordered_groups, ordered_groups[1:]):
            left_right = median([float(item["bbox"][2]) for item in left])
            right_left = median([float(item["bbox"][0]) for item in right])
            if left_right > right_left + page_width * 0.04:
                return None
        return ordered_groups

    for split_count in range(min(max_columns - 1, len(qualified_gaps)), 0, -1):
        groups = validated_groups(split_count)
        if groups:
            return groups
    return [items]


def _reading_order(blocks: list[dict[str, Any]], page_width: float) -> tuple[list[dict[str, Any]], float]:
    if not blocks:
        return [], 0.0
    usable = [item for item in blocks if _clean(item.get("text", ""))]
    if not usable:
        return [], 0.0
    spanning = [item for item in usable if float(item["bbox"][2]) - float(item["bbox"][0]) >= page_width * 0.56]
    non_spanning = [item for item in usable if item not in spanning]
    detection_items = [
        item
        for item in non_spanning
        if float(item["bbox"][2]) - float(item["bbox"][0]) >= page_width * 0.20
        and len(_normalized_compare_text(str(item.get("text") or ""))) >= 20
    ]
    detected_columns = _column_groups(detection_items, page_width)
    if len(detected_columns) == 1:
        ordered = sorted(usable, key=lambda item: (round(float(item["bbox"][1]), 1), float(item["bbox"][0])))
        confidence = 0.96
        for item in ordered:
            item["column"] = 0
    else:
        def median_x0(column: list[dict[str, Any]]) -> float:
            values = sorted(float(item["bbox"][0]) for item in column)
            middle = len(values) // 2
            return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0

        anchors = [median_x0(column) for column in detected_columns]
        columns = [[] for _ in anchors]
        for item in non_spanning:
            column_index = min(range(len(anchors)), key=lambda index: abs(float(item["bbox"][0]) - anchors[index]))
            columns[column_index].append(item)
        for column_index, column in enumerate(columns):
            for item in column:
                item["column"] = column_index
        for item in spanning:
            item["column"] = -1
        boundaries = sorted(spanning, key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0])))
        ordered = []
        cursor = float("-inf")
        for boundary in boundaries + [None]:
            limit = float(boundary["bbox"][1]) if boundary else float("inf")
            segment = [item for item in usable if item not in spanning and cursor <= float(item["bbox"][1]) < limit]
            for column in columns:
                ordered.extend(sorted((item for item in segment if item in column), key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0]))))
            if boundary:
                ordered.append(boundary)
                cursor = float(boundary["bbox"][3])
        seen: set[int] = set()
        ordered = [item for item in ordered if not (id(item) in seen or seen.add(id(item)))]
        confidence = (0.88 if spanning else 0.82) if len(columns) == 2 else (0.84 if spanning else 0.78)
    for index, item in enumerate(ordered, 1):
        item["reading_order"] = index
    return ordered, confidence


def _rotate_blocks_to_page(blocks: list[dict[str, Any]], page: Any) -> list[dict[str, Any]]:
    if not int(getattr(page, "rotation", 0) or 0):
        return blocks
    try:
        import fitz

        matrix = page.rotation_matrix
        rotated = []
        for item in blocks:
            value = dict(item)
            rect = fitz.Rect(*item["bbox"]) * matrix
            value["bbox"] = [round(float(rect.x0), 3), round(float(rect.y0), 3), round(float(rect.x1), 3), round(float(rect.y1), 3)]
            rotated.append(value)
        return rotated
    except Exception:
        return blocks


def _pymupdf_line_blocks(page: Any) -> list[dict[str, Any]]:
    records = []
    payload = page.get_text("dict")
    for parent_index, block in enumerate(payload.get("blocks", []), 1):
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if _clean(span.get("text", ""))]
            if not spans:
                continue
            spans.sort(key=lambda span: float(span.get("bbox", [0, 0, 0, 0])[0]))
            text = _clean(" ".join(str(span.get("text") or "") for span in spans))
            bbox_values = [span.get("bbox", [0, 0, 0, 0]) for span in spans]
            bbox = [
                round(min(float(value[0]) for value in bbox_values), 3),
                round(min(float(value[1]) for value in bbox_values), 3),
                round(max(float(value[2]) for value in bbox_values), 3),
                round(max(float(value[3]) for value in bbox_values), 3),
            ]
            sizes = [float(span.get("size") or 0.0) for span in spans if float(span.get("size") or 0.0) > 0]
            span_bold = [
                bool(int(span.get("flags") or 0) & 16) or bool(re.search(r"(?:bold|demi|semi|medi)", str(span.get("font") or ""), re.IGNORECASE))
                for span in spans
            ]
            span_lengths = [max(1, len(_clean(span.get("text", "")))) for span in spans]
            bold_characters = sum(length for length, bold in zip(span_lengths, span_bold) if bold)
            total_characters = sum(span_lengths)
            font_bold_ratio = round(bold_characters / max(1, total_characters), 4)
            font_bold = font_bold_ratio >= 0.8
            records.append({
                "bbox": bbox,
                "text": text,
                "source": "pymupdf",
                "confidence": 1.0,
                "parent_block": parent_index,
                "font_size": round(max(sizes), 3) if sizes else None,
                "font_bold": font_bold,
                "font_bold_ratio": font_bold_ratio,
            })
    return records


def _merge_native_hyphenated_lines(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    merged: list[dict[str, Any]] = []
    repairs = 0
    for record in records:
        current = dict(record)
        if not merged:
            merged.append(current)
            continue
        previous = merged[-1]
        previous_text = str(previous.get("text") or "")
        current_text = str(current.get("text") or "")
        match_left = re.search(r"([A-Za-z]{2,})-$", previous_text)
        match_right = re.match(r"([A-Za-z]{2,})", current_text)
        same_parent = previous.get("parent_block") is not None and previous.get("parent_block") == current.get("parent_block")
        if not same_parent or not match_left or not match_right:
            merged.append(current)
            continue
        combined_word = f"{match_left.group(1)}{match_right.group(1)}".casefold()
        separator = "" if combined_word in OCR_PROTECTED_WORDS or len(match_left.group(1)) <= 3 else "-"
        joined_text = f"{previous_text[:-1]}{separator}{current_text.lstrip()}"
        previous_bbox = previous.get("bbox") or [0, 0, 0, 0]
        current_bbox = current.get("bbox") or previous_bbox
        previous.update({
            "text": _clean(joined_text),
            "bbox": [
                round(min(float(previous_bbox[0]), float(current_bbox[0])), 3),
                round(min(float(previous_bbox[1]), float(current_bbox[1])), 3),
                round(max(float(previous_bbox[2]), float(current_bbox[2])), 3),
                round(max(float(previous_bbox[3]), float(current_bbox[3])), 3),
            ],
            "confidence": min(float(previous.get("confidence") or 1.0), float(current.get("confidence") or 1.0)),
            "font_size": max(float(previous.get("font_size") or 0.0), float(current.get("font_size") or 0.0)) or None,
            "font_bold": bool(previous.get("font_bold")) and bool(current.get("font_bold")),
            "native_hyphenation_repairs": int(previous.get("native_hyphenation_repairs") or 0) + 1,
        })
        repairs += 1
    return merged, repairs


def _poppler_pages(path: Path, timeout: int = 30) -> tuple[list[str], str | None]:
    executable = shutil.which("pdftotext")
    if not executable:
        return [], "pdftotext unavailable"
    try:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "paper.txt"
            subprocess.run([executable, "-layout", str(path), str(target)], check=True, timeout=timeout, capture_output=True)
            return target.read_text(encoding="utf-8", errors="replace").split("\f"), None
    except Exception as exc:
        return [], str(exc)


def _pdfplumber_blocks(path: Path, page_number: int) -> list[dict[str, Any]]:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as document:
            page = document.pages[page_number - 1]
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False) or []
        rows: list[list[dict[str, Any]]] = []
        for word in sorted(words, key=lambda item: (float(item.get("top", 0.0)), float(item.get("x0", 0.0)))):
            row = next((items for items in rows if abs(float(items[0].get("top", 0.0)) - float(word.get("top", 0.0))) <= 3.0), None)
            if row is None:
                row = []
                rows.append(row)
            row.append(word)
        blocks = []
        for row in rows:
            row.sort(key=lambda item: float(item.get("x0", 0.0)))
            text = _clean(" ".join(str(item.get("text") or "") for item in row))
            if text:
                blocks.append({
                    "bbox": [min(float(item["x0"]) for item in row), min(float(item["top"]) for item in row), max(float(item["x1"]) for item in row), max(float(item["bottom"]) for item in row)],
                    "text": text,
                    "source": "pdfplumber",
                    "confidence": 0.92,
                })
        return blocks
    except Exception:
        return []


def _pdf_metadata(path: Path) -> dict[str, Any]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise ValueError("PDF is encrypted and cannot be opened without a password")
        return {"page_count": len(reader.pages), "encrypted": bool(reader.is_encrypted), "metadata": {str(key): str(value) for key, value in (reader.metadata or {}).items()}}
    except ImportError:
        return {"page_count": None, "encrypted": None, "metadata": {}, "warning": "pypdf unavailable"}


def _ocr_records(image_path: Path, engine: str, lang: str, adapter: Callable | None, rapidocr_threads: int = 1) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    if adapter:
        return list(adapter(image_path, lang) or []), "adapter", {}
    from ..reference_text_extractor import run_easyocr, run_paddle_ocr, run_rapidocr_detailed

    requested = engine
    if requested == "auto":
        requested = "rapidocr"
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception:
            requested = "easyocr"
            try:
                import easyocr  # noqa: F401
            except Exception:
                requested = "paddle"
    if requested == "rapidocr":
        records, diagnostics = run_rapidocr_detailed(image_path, lang, threads=rapidocr_threads)
        return records, "rapidocr", diagnostics
    if requested == "easyocr":
        return run_easyocr(image_path, lang), "easyocr", {}
    if requested == "paddle":
        return run_paddle_ocr(image_path, lang), "paddle", {}
    return [], "off", {}


def _group_ocr_words(records: list[dict[str, Any]], image_width: float) -> list[dict[str, Any]]:
    words = []
    for record in records:
        quad = record.get("quad") or []
        if len(quad) < 4 or not _clean(record.get("text", "")):
            continue
        xs = [float(point[0]) for point in quad]
        ys = [float(point[1]) for point in quad]
        words.append({
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "text": _clean(record.get("text", "")),
            "confidence": float(record.get("confidence") or 0.0),
        })
    words.sort(key=lambda item: ((item["bbox"][1] + item["bbox"][3]) / 2.0, item["bbox"][0]))
    lines: list[dict[str, Any]] = []
    for word in words:
        bbox = word["bbox"]
        center_y = (bbox[1] + bbox[3]) / 2.0
        height = max(1.0, bbox[3] - bbox[1])
        line = next((
            item for item in reversed(lines[-12:])
            if abs(center_y - item["center_y"]) <= max(height, item["mean_height"]) * 0.62
            and bbox[0] >= item["bbox"][0] - image_width * 0.08
        ), None)
        if line is None:
            lines.append({"words": [word], "bbox": list(bbox), "center_y": center_y, "mean_height": height})
            continue
        line["words"].append(word)
        line["bbox"] = [min(line["bbox"][0], bbox[0]), min(line["bbox"][1], bbox[1]), max(line["bbox"][2], bbox[2]), max(line["bbox"][3], bbox[3])]
        line["center_y"] = sum((item["bbox"][1] + item["bbox"][3]) / 2.0 for item in line["words"]) / len(line["words"])
        line["mean_height"] = sum(max(1.0, item["bbox"][3] - item["bbox"][1]) for item in line["words"]) / len(line["words"])

    grouped = []
    for line in lines:
        line["words"].sort(key=lambda item: item["bbox"][0])
        grouped.append({
            "bbox": line["bbox"],
            "text": _clean(" ".join(item["text"] for item in line["words"])),
            "confidence": round(sum(item["confidence"] for item in line["words"]) / max(1, len(line["words"])), 4),
        })
    grouped.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    heights = sorted(max(1.0, item["bbox"][3] - item["bbox"][1]) for item in grouped)
    median_height = heights[len(heights) // 2] if heights else 12.0
    parent = 0
    previous_by_column: dict[int, dict[str, Any]] = {}
    for item in grouped:
        center_x = (item["bbox"][0] + item["bbox"][2]) / 2.0
        width = item["bbox"][2] - item["bbox"][0]
        column = 2 if width >= image_width * 0.62 else 0 if center_x <= image_width / 2.0 else 1
        previous = previous_by_column.get(column)
        gap = item["bbox"][1] - previous["bbox"][3] if previous else float("inf")
        starts_new = bool(re.match(r"^(?:abstract|\d+(?:\.\d+)*\s+|figure|fig\.|table)\b", item["text"], re.IGNORECASE))
        if previous is None or gap > median_height * 1.8 or starts_new:
            parent += 1
        item["parent_block"] = parent
        previous_by_column[column] = item
    return grouped


def _assign_ocr_parent_blocks(lines: list[dict[str, Any]], image_width: float) -> list[dict[str, Any]]:
    ordered = sorted(lines, key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0])))
    heights = sorted(max(1.0, float(item["bbox"][3]) - float(item["bbox"][1])) for item in ordered)
    median_height = heights[len(heights) // 2] if heights else 12.0
    parent = 0
    previous_by_column: dict[int, dict[str, Any]] = {}
    last_item: dict[str, Any] | None = None
    for item in ordered:
        center_x = (float(item["bbox"][0]) + float(item["bbox"][2])) / 2.0
        width = float(item["bbox"][2]) - float(item["bbox"][0])
        column = 2 if width >= image_width * 0.62 else 0 if center_x <= image_width / 2.0 else 1
        previous = previous_by_column.get(column)
        if last_item and last_item.get("_caption_group"):
            last_gap = float(item["bbox"][1]) - float(last_item["bbox"][3])
            last_height = max(
                median_height,
                float(item["bbox"][3]) - float(item["bbox"][1]),
                float(last_item["bbox"][3]) - float(last_item["bbox"][1]),
            )
            if last_gap <= last_height * 1.15:
                previous = last_item
        gap = float(item["bbox"][1]) - float(previous["bbox"][3]) if previous else float("inf")
        local_height = max(
            median_height,
            float(item["bbox"][3]) - float(item["bbox"][1]),
            (float(previous["bbox"][3]) - float(previous["bbox"][1])) if previous else 0.0,
        )
        text = str(item.get("text") or "")
        starts_new = bool(re.match(r"^(?:abstract|\d+(?:\.\d+)*\s+|figure|fig\.|table)\b", text, re.IGNORECASE))
        starts_caption = bool(re.match(r"^(?:figure|fig\.|table)\b", text, re.IGNORECASE))
        continuing_caption = bool(previous and previous.get("_caption_group") and gap <= local_height * 1.15 and not starts_new)
        paragraph_break = bool(previous and not continuing_caption and str(previous.get("text") or "").rstrip().endswith((".", ":")) and gap > local_height * 0.45)
        if previous is None or gap > local_height * 1.15 or starts_new or paragraph_break:
            parent += 1
        item["parent_block"] = parent
        item["_caption_group"] = starts_caption or continuing_caption
        previous_by_column[column] = item
        last_item = item
    return ordered


def _filter_ocr_margin_noise(records: list[dict[str, Any]], image_width: float) -> tuple[list[dict[str, Any]], int]:
    anchors = [
        item
        for item in records
        if len(_normalized_compare_text(str(item.get("text") or ""))) >= 20
        and float(item["bbox"][2]) - float(item["bbox"][0]) >= image_width * 0.30
    ]
    if len(anchors) < 3:
        return records, 0
    left = sorted(float(item["bbox"][0]) for item in anchors)[max(0, len(anchors) // 10 - 1)]
    right_values = sorted(float(item["bbox"][2]) for item in anchors)
    right = right_values[min(len(right_values) - 1, len(right_values) - max(1, len(anchors) // 10))]
    margin = image_width * 0.035
    kept = []
    removed = 0
    for item in records:
        bbox = item.get("bbox") or [0, 0, 0, 0]
        outside = float(bbox[2]) < left - margin or float(bbox[0]) > right + margin
        width = max(1.0, float(bbox[2]) - float(bbox[0]))
        height = max(1.0, float(bbox[3]) - float(bbox[1]))
        short = len(_normalized_compare_text(str(item.get("text") or ""))) < 12
        vertical = height > width * 1.15
        outer_band = float(bbox[2]) < image_width * 0.12 or float(bbox[0]) > image_width * 0.88
        compact_margin_fragment = outer_band and short and (vertical or width < image_width * 0.08)
        if (outside and (short or vertical)) or compact_margin_fragment:
            removed += 1
            continue
        kept.append(item)
    return kept, removed


def _repeated_margin_signature(text: str) -> str:
    value = _clean(text).casefold()
    value = re.sub(r"\d+", "#", value)
    value = re.sub(r"\s+", " ", value).strip(" |.-_")
    return value


def _semantic_margin_region(page: dict[str, Any], bbox: list[float] | tuple[float, ...]) -> str | None:
    width = float(page.get("width") or 0.0)
    height = float(page.get("height") or 0.0)
    if width <= 0 or height <= 0:
        return None
    rotation = int(page.get("rotation") or 0) % 360
    if rotation == 90:
        if float(bbox[0]) >= width * 0.88:
            return "header"
        if float(bbox[2]) <= width * 0.12:
            return "footer"
    elif rotation == 180:
        if float(bbox[1]) >= height * 0.88:
            return "header"
        if float(bbox[3]) <= height * 0.12:
            return "footer"
    elif rotation == 270:
        if float(bbox[2]) <= width * 0.12:
            return "header"
        if float(bbox[0]) >= width * 0.88:
            return "footer"
    else:
        if float(bbox[3]) <= height * 0.12:
            return "header"
        if float(bbox[1]) >= height * 0.88:
            return "footer"
    return None


def _remove_repeated_margin_noise(pages: list[dict[str, Any]]) -> int:
    if len(pages) < 3:
        return 0
    occurrences: dict[tuple[str, str], set[int]] = {}
    candidates: dict[tuple[int, str], tuple[str, str]] = {}
    for page in pages:
        page_number = int(page.get("page") or 0)
        for block in page.get("blocks", []):
            bbox = block.get("bbox")
            text = str(block.get("text") or "").strip()
            if str(block.get("kind") or "") == "heading" or bool(block.get("font_bold")):
                continue
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not text or len(text) > 140 or len(_lexical_units(text)) > 12 or _cjk_character_count(text) > 36:
                continue
            region = _semantic_margin_region(page, bbox)
            if not region:
                continue
            signature = _repeated_margin_signature(text)
            if not signature:
                continue
            key = (region, signature)
            occurrences.setdefault(key, set()).add(page_number)
            candidates[(page_number, str(block.get("id") or ""))] = key

    threshold = max(3, (len(pages) + 3) // 4)
    repeated = {key for key, page_numbers in occurrences.items() if len(page_numbers) >= threshold}
    if not repeated:
        return 0

    removed = 0
    for page in pages:
        page_number = int(page.get("page") or 0)
        kept = []
        page_removed = 0
        for block in page.get("blocks", []):
            key = candidates.get((page_number, str(block.get("id") or "")))
            if key in repeated:
                page_removed += 1
                continue
            kept.append(block)
        if not page_removed:
            continue
        for order, block in enumerate(kept, 1):
            block["reading_order"] = order
        page_text = "\n\n".join(str(item.get("text") or "") for item in kept)
        page.update({
            "blocks": kept,
            "text": page_text,
            "char_count": len(page_text),
            "replacement_character_rate": _replacement_rate(page_text),
            "mojibake_rate": _mojibake_rate(page_text),
            "column_count": max((int(item.get("column", 0)) for item in kept), default=0) + 1,
            "repeated_margin_noise_removed": page_removed,
        })
        removed += page_removed
    return removed


def _ocr_page(page: Any, page_number: int, engine: str, lang: str, adapter: Callable | None, rapidocr_threads: int = 1) -> tuple[list[dict[str, Any]], str, str | None, dict[str, Any]]:
    try:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / f"page_{page_number:03d}.png"
            dpi = 72 if adapter is None and engine in {"auto", "easyocr", "rapidocr"} else 160
            render_started = time.monotonic()
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            pixmap.save(str(target))
            render_seconds = time.monotonic() - render_started
            records, used_engine, engine_diagnostics = _ocr_records(target, engine, lang, adapter, rapidocr_threads=rapidocr_threads)
            postprocess_started = time.monotonic()
            spacing_repairs = 0
            for record in records:
                repaired, count = _repair_ocr_spacing(record.get("text", ""))
                record["text"] = repaired
                spacing_repairs += count
            if used_engine != "rapidocr":
                records = _group_ocr_words(records, float(pixmap.width))
            else:
                normalized_records = []
                for record in records:
                    quad = record.get("quad") or []
                    if len(quad) < 4:
                        continue
                    xs = [float(point[0]) for point in quad]
                    ys = [float(point[1]) for point in quad]
                    normalized_records.append({"bbox": [min(xs), min(ys), max(xs), max(ys)], "text": _clean(record.get("text", "")), "confidence": float(record.get("confidence") or 0.0)})
                records = _assign_ocr_parent_blocks(normalized_records, float(pixmap.width))
            records, margin_noise_removed = _filter_ocr_margin_noise(records, float(pixmap.width))
            blocks = []
            scale_x = float(page.rect.width) / max(1, pixmap.width)
            scale_y = float(page.rect.height) / max(1, pixmap.height)
            for record in records:
                raw_bbox = record.get("bbox")
                if not raw_bbox:
                    continue
                blocks.append({
                    "bbox": [float(raw_bbox[0]) * scale_x, float(raw_bbox[1]) * scale_y, float(raw_bbox[2]) * scale_x, float(raw_bbox[3]) * scale_y],
                    "text": _clean(record.get("text", "")),
                    "source": used_engine,
                    "confidence": round(float(record.get("confidence") or 0.0), 4),
                    "parent_block": record.get("parent_block"),
                })
            return blocks, used_engine, None, {
                "margin_noise_removed": margin_noise_removed,
                "spacing_repairs": spacing_repairs,
                "render_seconds": round(render_seconds, 4),
                "postprocess_seconds": round(time.monotonic() - postprocess_started, 4),
                **engine_diagnostics,
            }
    except Exception as exc:
        return [], engine, str(exc), {"margin_noise_removed": 0, "spacing_repairs": 0}


def _rapidocr_worker_count(engine: str, adapter: Callable | None, page_count: int) -> int:
    if adapter is not None or page_count < 2 or engine not in {"auto", "rapidocr"}:
        return 1
    if engine == "auto":
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception:
            return 1
    cpu_count = int(os.cpu_count() or 1)
    default_workers = 4 if cpu_count >= 8 else 2 if cpu_count >= 4 else 1
    try:
        configured = int(os.getenv("RFS_OCR_WORKERS") or default_workers)
    except ValueError:
        configured = default_workers
    return max(1, min(int(page_count), configured, cpu_count))


def _deadline_ocr_wave(
    path: Path,
    page_numbers: list[int],
    engine: str,
    lang: str,
    deadline_at: float,
) -> list[tuple[int, tuple[list[dict[str, Any]], str, str | None, dict[str, Any]], float]]:
    """Run OCR pages in killable child processes and preserve completed results."""
    cutoff = max(time.monotonic(), float(deadline_at) - 20.0)
    worker_threads = 2 if len(page_numbers) == 1 and engine in {"auto", "rapidocr"} else 1
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    with tempfile.TemporaryDirectory() as temp:
        processes: dict[int, dict[str, Any]] = {}
        for page_number in page_numbers:
            output = Path(temp) / f"page_{page_number:03d}.json"
            command = [
                sys.executable,
                "-m",
                "rfs.paper_to_image.ocr_worker",
                "--paper",
                str(path),
                "--page",
                str(page_number),
                "--engine",
                engine,
                "--lang",
                lang,
                "--threads",
                str(worker_threads),
                "--out",
                str(output),
            ]
            started = time.monotonic()
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creation_flags,
                )
                processes[page_number] = {"process": process, "output": output, "started": started, "launch_error": None}
            except Exception as exc:
                processes[page_number] = {"process": None, "output": output, "started": started, "launch_error": str(exc)}

        pending = {page for page, item in processes.items() if item["process"] is not None}
        while pending and time.monotonic() < cutoff:
            finished = {page for page in pending if processes[page]["process"].poll() is not None}
            pending.difference_update(finished)
            if pending:
                time.sleep(0.02)

        timed_out = set(pending)
        for page_number in timed_out:
            process = processes[page_number]["process"]
            try:
                process.terminate()
            except Exception:
                pass
        for page_number in timed_out:
            process = processes[page_number]["process"]
            try:
                process.wait(timeout=1.0)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass

        results = []
        for page_number in page_numbers:
            item = processes[page_number]
            process = item["process"]
            elapsed = time.monotonic() - float(item["started"])
            stderr = ""
            if process is not None:
                try:
                    _stdout, stderr = process.communicate(timeout=0.2)
                except Exception:
                    stderr = ""
            if item["launch_error"]:
                result = ([], engine, f"OCR worker launch failed: {item['launch_error']}", {"worker_process": True})
            elif page_number in timed_out:
                result = ([], engine, "OCR exceeded extraction deadline", {"worker_process": True, "timed_out": True})
            elif item["output"].exists():
                try:
                    payload = json.loads(item["output"].read_text(encoding="utf-8"))
                    result = (
                        list(payload.get("blocks") or []),
                        str(payload.get("engine") or engine),
                        str(payload.get("error")) if payload.get("error") else None,
                        {"worker_process": True, **dict(payload.get("diagnostics") or {})},
                    )
                    elapsed = float(payload.get("elapsed_seconds") or elapsed)
                except Exception as exc:
                    result = ([], engine, f"OCR worker returned invalid output: {exc}", {"worker_process": True})
            else:
                detail = stderr.strip() or f"worker exited with code {getattr(process, 'returncode', None)}"
                result = ([], engine, f"OCR worker failed: {detail}", {"worker_process": True})
            results.append((page_number, result, elapsed))
        return results


def _prioritize_ocr_candidates(
    pages: list[dict[str, Any]],
    candidates: list[int],
    max_pages: int,
) -> tuple[list[int], list[dict[str, Any]]]:
    if max_pages <= 0 or not candidates:
        return [], []
    page_count = max(1, len(pages))
    signals = {
        "overview_figure": re.compile(r"\b(?:figure|fig\.)\s*[12]\b.*\b(?:overview|framework|architecture|pipeline|system|model)\b", re.IGNORECASE | re.DOTALL),
        "method": re.compile(r"\b(?:methods?|methodology|approach|architecture|system overview|framework)\b", re.IGNORECASE),
        "abstract": re.compile(r"\babstract\b", re.IGNORECASE),
        "conclusion": re.compile(r"\b(?:conclusions?|discussion)\b", re.IGNORECASE),
        "caption": re.compile(r"\b(?:figure|fig\.|table)\s*\d", re.IGNORECASE),
    }
    scored: list[tuple[int, int, list[str]]] = []
    for page_number in candidates:
        page = pages[page_number - 1] if 0 < page_number <= len(pages) else {}
        text = str(page.get("text") or "")
        reasons: list[str] = []
        score = 0
        for name, weight in (("overview_figure", 14), ("method", 10), ("abstract", 9), ("conclusion", 8), ("caption", 5)):
            if signals[name].search(text):
                score += weight
                reasons.append(name)
        if page_number == 1:
            score += 7
            reasons.append("first_page")
        elif page_number <= 3:
            score += 3
            reasons.append("early_page")
        scored.append((score, page_number, reasons))

    selected: list[int] = []
    reason_map: dict[int, list[str]] = {}
    for score, page_number, reasons in sorted(scored, key=lambda item: (-item[0], item[1])):
        if score <= 0 or len(selected) >= max_pages:
            break
        selected.append(page_number)
        reason_map[page_number] = reasons

    anchors = [
        1,
        min(2, page_count),
        min(3, page_count),
        min(4, page_count),
        max(1, round(page_count * 0.85)),
        max(1, round(page_count * 0.50)),
    ]
    for anchor in anchors:
        if len(selected) >= max_pages:
            break
        if anchor in selected:
            continue
        available = [value for value in candidates if value not in selected]
        if not available:
            break
        page_number = min(available, key=lambda value: (abs(value - anchor), value))
        selected.append(page_number)
        reason_map.setdefault(page_number, []).append(f"coverage_anchor_{anchor}")

    for page_number in candidates:
        if len(selected) >= max_pages:
            break
        if page_number not in selected:
            selected.append(page_number)
            reason_map.setdefault(page_number, []).append("remaining_candidate")

    details = [
        {"page": page_number, "rank": rank, "reasons": reason_map.get(page_number, [])}
        for rank, page_number in enumerate(selected, 1)
    ]
    return selected, details


def _read_pdf_pages(
    path: Path,
    max_chars: int,
    deadline_at: float | None,
    ocr_engine: str,
    ocr_lang: str,
    ocr_adapter: Callable | None,
    max_ocr_pages: int,
    ocr_rescue_min_remaining: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError(f"PyMuPDF is required for PDF extraction: {exc}") from exc

    metadata = _pdf_metadata(path)
    started = time.monotonic()
    document = fitz.open(str(path))
    poppler_text, poppler_warning = _poppler_pages(path)
    pages: list[dict[str, Any]] = []
    warnings: list[str] = [poppler_warning] if poppler_warning else []
    used_chars = 0
    ocr_candidates: list[int] = []
    try:
        for index, page in enumerate(document, 1):
            native_width = float(page.mediabox.width) if int(page.rotation or 0) else float(page.rect.width)
            raw_blocks, hyphenation_repairs = _merge_native_hyphenated_lines(_pymupdf_line_blocks(page))
            ordered, order_confidence = _reading_order(raw_blocks, native_width)
            if len(_normalized_compare_text(" ".join(item["text"] for item in ordered))) < 80:
                fallback_blocks, fallback_hyphenation_repairs = _merge_native_hyphenated_lines(_pdfplumber_blocks(path, index))
                fallback_ordered, fallback_confidence = _reading_order(fallback_blocks, native_width)
                if len(_normalized_compare_text(" ".join(item["text"] for item in fallback_ordered))) > len(_normalized_compare_text(" ".join(item["text"] for item in ordered))):
                    ordered, order_confidence = fallback_ordered, min(fallback_confidence, 0.9)
                    hyphenation_repairs = fallback_hyphenation_repairs
            ordered = _rotate_blocks_to_page(ordered, page)
            for block_index, block in enumerate(ordered, 1):
                block["id"] = f"P{index:03d}_B{block_index:03d}"
                block["kind"] = _block_kind(block["text"], (block["bbox"][2] - block["bbox"][0]) / max(1.0, float(page.rect.width)))
            page_text = "\n\n".join(item["text"] for item in ordered)
            poppler_page = poppler_text[index - 1] if index - 1 < len(poppler_text) else ""
            native_norm = _normalized_compare_text(page_text)
            poppler_norm = _normalized_compare_text(poppler_page)
            order_agreement = round(SequenceMatcher(None, native_norm[:20000], poppler_norm[:20000]).ratio(), 4) if native_norm and poppler_norm else None
            agreement = _token_overlap_agreement(page_text, poppler_page)
            abnormal = len(native_norm) < 80 or _replacement_rate(page_text) > 0.005 or _mojibake_rate(page_text) > 0.005 or (agreement is not None and agreement < 0.65)
            if abnormal:
                ocr_candidates.append(index)
            pages.append({
                "page": index,
                "width": round(float(page.rect.width), 3),
                "height": round(float(page.rect.height), 3),
                "rotation": int(page.rotation or 0),
                "column_count": max((int(item.get("column", 0)) for item in ordered), default=0) + 1,
                "blocks": ordered,
                "text": page_text,
                "char_count": len(page_text),
                "replacement_character_rate": _replacement_rate(page_text),
                "mojibake_rate": _mojibake_rate(page_text),
                "poppler_agreement": agreement,
                "poppler_order_agreement": order_agreement,
                "reading_order_confidence": order_confidence,
                "native_hyphenation_repair_count": hyphenation_repairs,
                "used_ocr": False,
            })
            used_chars += len(page_text)
            if used_chars >= max_chars and "document text exceeds evidence budget; evidence will be sampled across all pages" not in warnings:
                warnings.append("document text exceeds evidence budget; evidence will be sampled across all pages")
    finally:
        pass

    ocr_pages: list[int] = []
    ocr_page_durations: list[dict[str, Any]] = []
    prioritized: list[int] = []
    ocr_priority: list[dict[str, Any]] = []
    ocr_worker_count = 1
    if ocr_engine != "off":
        prioritized, ocr_priority = _prioritize_ocr_candidates(pages, ocr_candidates, max_ocr_pages)
        ocr_worker_count = _rapidocr_worker_count(ocr_engine, ocr_adapter, len(prioritized))

        def consume_ocr_result(page_number: int, result: tuple[list[dict[str, Any]], str, str | None, dict[str, Any]], ocr_elapsed: float) -> None:
            blocks, used_engine, error, ocr_diagnostics = result
            ocr_page_durations.append({"page": page_number, "engine": used_engine, "elapsed_seconds": round(ocr_elapsed, 3), "success": not bool(error), **ocr_diagnostics})
            if error:
                warnings.append(f"page {page_number} OCR unavailable: {error}")
                return
            current = pages[page_number - 1]
            ordered, order_confidence = _reading_order(blocks, float(current["width"]))
            for block_index, block in enumerate(ordered, 1):
                block["id"] = f"P{page_number:03d}_B{block_index:03d}"
                block["kind"] = _block_kind(block["text"], (block["bbox"][2] - block["bbox"][0]) / max(1.0, float(current["width"])))
            ocr_text = "\n\n".join(item["text"] for item in ordered)
            if len(_normalized_compare_text(ocr_text)) > len(_normalized_compare_text(current["text"])):
                current.update({
                    "blocks": ordered,
                    "text": ocr_text,
                    "char_count": len(ocr_text),
                    "replacement_character_rate": _replacement_rate(ocr_text),
                    "mojibake_rate": _mojibake_rate(ocr_text),
                    "reading_order_confidence": order_confidence,
                    "column_count": max((int(item.get("column", 0)) for item in ordered), default=0) + 1,
                    "used_ocr": True,
                    "ocr_engine": used_engine,
                    "ocr_margin_noise_removed": int(ocr_diagnostics.get("margin_noise_removed") or 0),
                    "native_hyphenation_repair_count": 0,
                })
                ocr_pages.append(page_number)

        def deadline_allows_wave(rescue_page: bool = False) -> bool:
            if deadline_at is not None:
                remaining = deadline_at - time.monotonic()
                if rescue_page:
                    if remaining < max(25.0, float(ocr_rescue_min_remaining)):
                        warnings.append("OCR stopped to preserve deadline validation budget")
                        return False
                    return True
                completed_times = [float(item["elapsed_seconds"]) for item in ocr_page_durations if isinstance(item.get("elapsed_seconds"), (int, float))]
                estimated = (max(completed_times) * 1.25) if completed_times else 45.0
                if remaining < estimated + 20:
                    warnings.append("OCR stopped to preserve deadline validation budget")
                    return False
            return True

        if deadline_at is not None and ocr_adapter is None:
            start = 0
            while start < len(prioritized):
                rescue_page = start > 0
                if not deadline_allows_wave(rescue_page=rescue_page):
                    break
                wave_size = 1 if rescue_page else ocr_worker_count
                batch = prioritized[start:start + wave_size]
                for page_number, result, ocr_elapsed in _deadline_ocr_wave(path, batch, ocr_engine, ocr_lang, deadline_at):
                    consume_ocr_result(page_number, result, ocr_elapsed)
                start += wave_size
        elif ocr_worker_count > 1:
            def isolated_ocr(page_number: int) -> tuple[tuple[list[dict[str, Any]], str, str | None, dict[str, Any]], float]:
                ocr_started = time.monotonic()
                try:
                    local_document = fitz.open(str(path))
                    try:
                        result = _ocr_page(local_document[page_number - 1], page_number, ocr_engine, ocr_lang, ocr_adapter, rapidocr_threads=1)
                        return result, time.monotonic() - ocr_started
                    finally:
                        local_document.close()
                except Exception as exc:
                    return ([], ocr_engine, str(exc), {"margin_noise_removed": 0}), time.monotonic() - ocr_started

            with ThreadPoolExecutor(max_workers=ocr_worker_count) as pool:
                for start in range(0, len(prioritized), ocr_worker_count):
                    if not deadline_allows_wave():
                        break
                    batch = prioritized[start:start + ocr_worker_count]
                    futures = {page_number: pool.submit(isolated_ocr, page_number) for page_number in batch}
                    for page_number in batch:
                        result, ocr_elapsed = futures[page_number].result()
                        consume_ocr_result(page_number, result, ocr_elapsed)
        else:
            rapidocr_threads = 2 if ocr_engine in {"auto", "rapidocr"} and ocr_adapter is None else 1
            for page_number in prioritized:
                if not deadline_allows_wave():
                    break
                ocr_started = time.monotonic()
                result = _ocr_page(document[page_number - 1], page_number, ocr_engine, ocr_lang, ocr_adapter, rapidocr_threads=rapidocr_threads)
                consume_ocr_result(page_number, result, time.monotonic() - ocr_started)
    repeated_margin_noise_removed = _remove_repeated_margin_noise(pages)
    document.close()
    elapsed = round(time.monotonic() - started, 3)
    attempted_pages = [int(item["page"]) for item in ocr_page_durations if item.get("page")]
    successful_attempt_pages = [int(item["page"]) for item in ocr_page_durations if item.get("page") and item.get("success")]
    schedule_complete = set(prioritized).issubset(attempted_pages)
    run_complete = schedule_complete and set(attempted_pages).issubset(successful_attempt_pages)
    if not schedule_complete and "OCR schedule was not completed before the extraction deadline" not in warnings:
        warnings.append("OCR schedule was not completed before the extraction deadline")
    return pages, {
        "metadata": metadata,
        "ocr_candidate_pages": ocr_candidates,
        "ocr_priority_pages": prioritized,
        "ocr_priority": ocr_priority,
        "ocr_pages": ocr_pages,
        "ocr_page_durations": ocr_page_durations,
        "ocr_attempted_pages": attempted_pages,
        "ocr_successful_attempt_pages": successful_attempt_pages,
        "ocr_schedule_complete": schedule_complete,
        "ocr_run_complete": run_complete,
        "ocr_worker_count": ocr_worker_count,
        "ocr_rescue_min_remaining_seconds": float(ocr_rescue_min_remaining),
        "repeated_margin_noise_removed_count": repeated_margin_noise_removed,
        "native_hyphenation_repair_count": sum(int(page.get("native_hyphenation_repair_count") or 0) for page in pages),
        "warnings": warnings,
        "poppler_available": bool(poppler_text),
        "elapsed_seconds": elapsed,
    }


def _read_non_pdf_pages(path: Path, max_chars: int) -> tuple[list[dict[str, Any]], str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        loader = "python-docx"
        try:
            import docx

            document = docx.Document(str(path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)[:max_chars]
        except Exception as exc:
            raise RuntimeError(f"DOCX extraction failed: {exc}") from exc
    else:
        loader = "plain"
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    clean = _clean(text)
    paragraphs = [_clean(value) for value in re.split(r"\n\s*\n", clean) if _clean(value)]
    chunks = []
    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        if len(lines) > 1 and re.match(r"^(?:abstract|\d+(?:\.\d+)*\s+|[ivx]+[.)]\s+)", lines[0], re.IGNORECASE):
            chunks.extend([_clean(lines[0]), _clean("\n".join(lines[1:]))])
        else:
            chunks.append(paragraph)
    blocks = []
    for index, chunk in enumerate(chunks or [clean], 1):
        blocks.append({"id": f"P001_B{index:03d}", "bbox": None, "text": chunk, "kind": _block_kind(chunk), "source": loader, "confidence": 1.0, "reading_order": index})
    return [{"page": 1, "width": None, "height": None, "blocks": blocks, "text": clean, "char_count": len(clean), "replacement_character_rate": _replacement_rate(clean), "mojibake_rate": _mojibake_rate(clean), "poppler_agreement": None, "reading_order_confidence": 1.0, "used_ocr": False}], loader


def _heading_candidates(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings = []
    seen = set()
    body_started = False
    body_anchor: tuple[int, float] | None = None
    for page in pages:
        font_sizes = sorted(float(block.get("font_size")) for block in page.get("blocks", []) if isinstance(block.get("font_size"), (int, float)) and len(_normalized_compare_text(str(block.get("text") or ""))) >= 20)
        middle = len(font_sizes) // 2
        body_font_size = (font_sizes[middle] if len(font_sizes) % 2 else (font_sizes[middle - 1] + font_sizes[middle]) / 2.0) if font_sizes else None
        for block in page.get("blocks", []):
            lines = [_clean(value) for value in str(block.get("text", "")).splitlines() if _clean(value)]
            for line_index, line in enumerate(lines):
                if not 2 <= len(line) <= 140:
                    continue
                explicit = re.match(r"^(abstract|references|acknowledg(?:e)?ments?|appendix)$", line, re.IGNORECASE)
                numbered = re.match(r"^\s*((?:\d+(?:\.\d+)*)|(?:[ivx]+))[.)]?\s+(.{2,120})$", line, re.IGNORECASE)
                compact_line = _normalized_compare_text(line)
                block_bold = bool(block.get("font_bold"))
                font_size = float(block.get("font_size") or 0.0)
                first_line_alpha = next((char for char in line if char.isalpha()), "")
                heading_case = not first_line_alpha or not first_line_alpha.isascii() or first_line_alpha.isupper()
                known = len(line) <= 60 and not line.endswith((".", ",", ";")) and any(
                    compact_alias and heading_case and (compact_line == compact_alias or (block_bold and compact_line.startswith(compact_alias)))
                    for aliases in SECTION_ALIASES.values()
                    for alias in aliases
                    for compact_alias in [_normalized_compare_text(alias)]
                )
                block_y = float((block.get("bbox") or [0, 0, 0, 0])[1])
                after_anchor = body_anchor is not None and (int(page["page"]) > body_anchor[0] or block_y >= body_anchor[1])
                position_ok = after_anchor if body_anchor is not None else body_started
                size_ok = body_font_size is None or font_size >= body_font_size * 0.95
                typographic = position_ok and block_bold and size_ok and _looks_like_typographic_heading(line)
                if numbered:
                    title_candidate = numbered.group(2).strip()
                    first_alpha = next((char for char in title_candidate if char.isalpha()), "")
                    numbered_style = block.get("source") != "pymupdf" or body_font_size is None or block_bold or font_size >= body_font_size * 1.05
                    if not numbered_style:
                        first_alpha = ""
                    if not title_candidate or not title_candidate[0].isalpha():
                        first_alpha = ""
                    has_case = bool(first_alpha and first_alpha.lower() != first_alpha.upper())
                    if not first_alpha or (has_case and not first_alpha.isupper()) or re.search(r"[=±∑∫]", title_candidate) or title_candidate.endswith(".") or len(title_candidate) > 80 or len(title_candidate.split()) > 10:
                        numbered = None
                if not (explicit or numbered or known or typographic):
                    continue
                normalized = numbered.group(2).strip() if numbered else line.strip().rstrip(".:")
                key = (normalized.casefold(), int(page.get("page") or 0), str(block.get("id") or ""), line_index)
                if normalized and key not in seen:
                    seen.add(key)
                    headings.append({
                        "id": f"section_{len(headings) + 1:03d}",
                        "title": normalized,
                        "page": page["page"],
                        "block_id": block["id"],
                        "line_index": line_index,
                        "_candidate_type": "explicit" if explicit else "numbered" if numbered else "known" if known else "typographic",
                        "_bbox": block.get("bbox"),
                        "_font_size": font_size,
                        "_reading_order": int(block.get("reading_order") or 0),
                    })
                if body_anchor is None and (explicit or numbered or known):
                    body_anchor = (int(page["page"]), block_y)
                body_started = body_started or bool(explicit or numbered or known)
    merged: list[dict[str, Any]] = []
    for heading in headings:
        previous = merged[-1] if merged else None
        previous_bbox = previous.get("_bbox") if previous else None
        current_bbox = heading.get("_bbox")
        same_multiline_heading = bool(
            previous
            and previous.get("_candidate_type") == "typographic"
            and heading.get("_candidate_type") == "typographic"
            and int(previous.get("page") or 0) == int(heading.get("page") or 0)
            and int(heading.get("_reading_order") or 0) == int(previous.get("_reading_order") or 0) + 1
            and previous_bbox
            and current_bbox
            and float(current_bbox[1]) - float(previous_bbox[3]) <= max(float(previous.get("_font_size") or 0), float(heading.get("_font_size") or 0), 1.0) * 0.8
            and len(f"{previous.get('title', '')} {heading.get('title', '')}") <= 140
        )
        if same_multiline_heading:
            previous["title"] = _clean(f"{previous.get('title', '')} {heading.get('title', '')}").rstrip(".:")
            previous.setdefault("continuation_block_ids", []).append(str(heading.get("block_id") or ""))
            previous["_bbox"] = [
                min(float(previous_bbox[0]), float(current_bbox[0])),
                min(float(previous_bbox[1]), float(current_bbox[1])),
                max(float(previous_bbox[2]), float(current_bbox[2])),
                max(float(previous_bbox[3]), float(current_bbox[3])),
            ]
            previous["_reading_order"] = int(heading.get("_reading_order") or 0)
            continue
        merged.append(heading)
    for index, heading in enumerate(merged, 1):
        heading["id"] = f"section_{index:03d}"
    return [{key: value for key, value in heading.items() if not key.startswith("_")} for heading in merged[:80]]


def _document_index(pages: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    figures = []
    tables = []
    formulas = []
    for page in pages:
        page_blocks = page.get("blocks", [])
        for block_index, block in enumerate(page_blocks):
            record = {"page": page["page"], "block_id": block["id"], "bbox": block.get("bbox"), "caption": block.get("text", "")}
            if block.get("kind") == "caption":
                parent = block.get("parent_block")
                continuation = []
                for following in page_blocks[block_index + 1:]:
                    if parent is None or following.get("parent_block") != parent or re.match(r"^(figure|fig\.|table|图|圖|表)\s*[\d一二三四五六七八九十]", str(following.get("text") or ""), re.IGNORECASE):
                        break
                    continuation.append(str(following.get("text") or ""))
                if continuation:
                    record["caption"] = _clean(record["caption"] + " " + " ".join(continuation))
                figures.append({"id": f"figure_{len(figures) + 1:03d}", **record})
            elif block.get("kind") == "table":
                tables.append({"id": f"table_{len(tables) + 1:03d}", **record})
            elif block.get("kind") == "formula":
                formulas.append({"id": f"formula_{len(formulas) + 1:03d}", "page": page["page"], "block_id": block["id"], "bbox": block.get("bbox"), "text": block.get("text", "")})
    return {"summary": "Page-aware section, formula, table-caption, and figure-caption index.", "sections": sections, "formulas": formulas[:120], "tables": tables[:80], "figures": figures[:80]}


def _section_coverage(pages: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, bool]:
    candidates = ("\n".join(item["title"] for item in sections) + "\n" + "\n".join(page.get("text", "") for page in pages)).casefold()
    compact = _normalized_compare_text(candidates)
    return {
        name: any(re.search(rf"\b{re.escape(alias)}\b", candidates) or (_normalized_compare_text(alias) and _normalized_compare_text(alias) in compact) for alias in aliases)
        for name, aliases in SECTION_ALIASES.items()
    }


def _evidence_id(page: int, text: str, bbox: Any, kind: str) -> str:
    payload = json.dumps({"page": page, "text": _clean(text), "bbox": bbox, "kind": kind}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"E_P{int(page):03d}_{hashlib.sha1(payload).hexdigest()[:12]}"


def _build_evidence(pages: list[dict[str, Any]], sections: list[dict[str, Any]], document_index: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    section_positions = sorted(sections, key=lambda item: (item["page"], item.get("block_id", "")))
    evidence: list[dict[str, Any]] = []
    used = 0
    for figure in document_index.get("figures", []):
        text = _clean(figure.get("caption", ""))
        if not text or used + len(text) > max_chars:
            continue
        evidence.append({
            "id": _evidence_id(int(figure.get("page") or 0), text, figure.get("bbox"), "caption"),
            "page": figure.get("page"),
            "block_id": figure.get("block_id"),
            "bbox": figure.get("bbox"),
            "section_hint": "Figure Captions",
            "kind": "caption",
            "source": "pymupdf",
            "confidence": 1.0,
            "text": text,
            "char_count": len(text),
        })
        used += len(text)

    block_candidates: list[dict[str, Any]] = []
    for page in pages:
        for block in page.get("blocks", []):
            text = _clean(block.get("text", ""))
            if not text or block.get("kind") == "caption":
                continue
            block_id = str(block.get("id") or "")
            section = next(
                (
                    item["title"]
                    for item in reversed(section_positions)
                    if (int(item["page"]), str(item.get("block_id") or "")) <= (int(page["page"]), block_id)
                ),
                None,
            )
            block_candidates.append({
                "id": _evidence_id(int(page["page"]), text, block.get("bbox"), str(block.get("kind") or "paragraph")),
                "page": page["page"],
                "block_id": block_id,
                "bbox": block.get("bbox"),
                "section_hint": section,
                "kind": block.get("kind"),
                "source": block.get("source"),
                "confidence": block.get("confidence", 1.0),
                "text": text,
                "char_count": len(text),
            })

    selected_ids: set[str] = set()
    page_groups: dict[int, list[dict[str, Any]]] = {}
    for item in block_candidates:
        page_groups.setdefault(int(item["page"]), []).append(item)

    def add(item: dict[str, Any], max_length: int | None = None) -> bool:
        nonlocal used
        item_id = str(item["id"])
        if item_id in selected_ids or used >= max_chars:
            return False
        remaining = max_chars - used
        if remaining <= 0:
            return False
        value = dict(item)
        if max_length is not None and len(value["text"]) > max_length:
            value["text"] = value["text"][:max_length].rstrip()
            value["char_count"] = len(value["text"])
            value["id"] = _evidence_id(int(value["page"]), value["text"], value.get("bbox"), str(value.get("kind") or "paragraph"))
        if len(value["text"]) > remaining:
            if remaining < 40:
                return False
            value["text"] = value["text"][:remaining].rstrip()
            value["char_count"] = len(value["text"])
            value["id"] = _evidence_id(int(value["page"]), value["text"], value.get("bbox"), str(value.get("kind") or "paragraph"))
            item_id = str(value["id"])
        evidence.append(value)
        selected_ids.add(str(item["id"]))
        selected_ids.add(item_id)
        used += len(value["text"])
        return True

    # Reserve a representative block for every page before spending the budget
    # on long early sections. This keeps conclusions and appendices discoverable.
    representative_quota = max(80, min(600, max(1, max_chars - used) // max(1, len(page_groups))))
    for page_number in sorted(page_groups):
        candidates = page_groups[page_number]
        representative = max(
            candidates,
            key=lambda item: (
                1 if item.get("kind") in {"paragraph", "title"} else 0,
                min(len(str(item.get("text") or "")), 600),
            ),
        )
        add(representative, max_length=representative_quota)

    section_priority = {
        "abstract": 0,
        "conclusion": 1,
        "conclusions": 1,
        "discussion": 1,
        "method": 2,
        "methods": 2,
        "methodology": 2,
        "approach": 2,
        "architecture": 2,
        "framework": 2,
        "system overview": 2,
        "introduction": 3,
        "background": 3,
        "experiment": 4,
        "experiments": 4,
        "evaluation": 4,
        "results": 4,
    }

    def priority(item: dict[str, Any]) -> tuple[int, int, str]:
        section = str(item.get("section_hint") or "").casefold()
        text = str(item.get("text") or "")
        topology_definition = bool(re.search(
            r"\b(?:has|have|consists? of|comprises?|contains?)\b.{0,80}\b(?:stages?|components?|modules?|steps?)\b"
            r"|\b(?:assisted[ -]manual|semi[ -]automatic|fully automatic)\b"
            r"|\b(?:input|image|text|query|prompt)\b.{0,100}\b(?:encoder|decoder|retriever|generator)\b"
            r"|\b(?:encoder|decoder|retriever|generator)\b.{0,100}\b(?:output|prediction|representation|embedding)\b",
            text,
            re.IGNORECASE,
        ))
        rank = min((value for name, value in section_priority.items() if name in section), default=5)
        if topology_definition:
            rank = -1
        if item.get("kind") == "heading":
            rank = min(rank, 2)
        return rank, int(item.get("page") or 0), str(item.get("block_id") or "")

    for item in sorted(block_candidates, key=priority):
        add(item)

    document_order = {
        str(item["id"]): index
        for index, item in enumerate(block_candidates)
    }
    caption_count = sum(1 for item in evidence if item.get("kind") == "caption")
    caption_items = evidence[:caption_count]
    body_items = sorted(evidence[caption_count:], key=lambda item: (int(item.get("page") or 0), document_order.get(str(item.get("id")), 10**9), str(item.get("block_id") or "")))
    evidence = caption_items + body_items
    for index, item in enumerate(evidence, 1):
        item["legacy_id"] = f"E{index:04d}"
    return evidence


def _extraction_report(source: Path, pages: list[dict[str, Any]], index: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    readable = [page for page in pages if len(_normalized_compare_text(page.get("text", ""))) >= 80]
    readable_ratio = round(len(readable) / max(1, len(pages)), 4)
    ocr_count = sum(1 for page in pages if page.get("used_ocr"))
    candidate_count = len(details.get("ocr_candidate_pages", []))
    fully_scanned_source = bool(pages and candidate_count == len(pages))
    partial_scan = bool(fully_scanned_source and 0 < ocr_count < len(pages))
    pdf_type = "scanned" if fully_scanned_source else "mixed" if ocr_count and ocr_count < len(pages) else "scanned" if ocr_count else "born_digital"
    coverage = _section_coverage(pages, index.get("sections", []))
    bold_block_ids = {(int(page["page"]), str(block.get("id") or "")) for page in pages for block in page.get("blocks", []) if block.get("font_bold")}
    warnings = list(details.get("warnings", []))
    ocr_blocks = [block for page in pages if page.get("used_ocr") for block in page.get("blocks", []) if isinstance(block, dict)]
    ocr_confidences = [float(block.get("confidence") or 0.0) for block in ocr_blocks]
    mean_ocr_confidence = round(sum(ocr_confidences) / max(1, len(ocr_confidences)), 4) if ocr_blocks else None
    short_ocr_blocks = [block for block in ocr_blocks if len(_normalized_compare_text(str(block.get("text") or ""))) < 3]
    short_ocr_block_ratio = round(len(short_ocr_blocks) / max(1, len(ocr_blocks)), 4) if ocr_blocks else None
    sampled_scan_ready = bool(
        partial_scan
        and len(readable) >= min(3, len(pages))
        and coverage.get("abstract")
        and coverage.get("method")
        and mean_ocr_confidence is not None
        and mean_ocr_confidence >= 0.75
    )
    if readable_ratio < 0.6 and not sampled_scan_ready:
        warnings.append("fewer than 60% of pages contain reliable text")
    if sampled_scan_ready:
        warnings.append("fully scanned document was only partially OCRed; semantic scope is limited to sampled pages")
    if mean_ocr_confidence is not None and mean_ocr_confidence < 0.5:
        warnings.append("mean OCR confidence is below 0.50")
    if short_ocr_block_ratio is not None and short_ocr_block_ratio > 0.3:
        warnings.append("OCR output is highly fragmented")
    if not coverage.get("abstract") or not coverage.get("method"):
        warnings.append("abstract or method-like section was not confidently located")
    agreements = [page["poppler_agreement"] for page in pages if isinstance(page.get("poppler_agreement"), (int, float))]
    report_status = "fail" if (readable_ratio < 0.6 and not sampled_scan_ready) or (mean_ocr_confidence is not None and mean_ocr_confidence < 0.35) else "warning" if warnings else "pass"
    return {
        "summary": "PDF extraction quality and fallback report.",
        "status": report_status,
        "source_path": str(source),
        "pdf_type": pdf_type,
        "page_count": len(pages),
        "readable_page_count": len(readable),
        "readable_page_ratio": readable_ratio,
        "semantic_scope": "sampled_pages_only" if partial_scan else "full_document",
        "scientific_scope_complete": not partial_scan,
        "sampled_scan_ready": sampled_scan_ready,
        "empty_or_low_text_pages": [page["page"] for page in pages if page not in readable],
        "ocr_candidate_pages": details.get("ocr_candidate_pages", []),
        "ocr_priority_pages": details.get("ocr_priority_pages", []),
        "ocr_priority": details.get("ocr_priority", []),
        "ocr_pages": details.get("ocr_pages", []),
        "ocr_page_durations": details.get("ocr_page_durations", []),
        "ocr_attempted_pages": details.get("ocr_attempted_pages", []),
        "ocr_successful_attempt_pages": details.get("ocr_successful_attempt_pages", []),
        "ocr_schedule_complete": bool(details.get("ocr_schedule_complete", True)),
        "ocr_run_complete": bool(details.get("ocr_run_complete", True)),
        "ocr_worker_count": int(details.get("ocr_worker_count") or 1),
        "ocr_rescue_min_remaining_seconds": float(details.get("ocr_rescue_min_remaining_seconds") or 45.0),
        "repeated_margin_noise_removed_count": int(details.get("repeated_margin_noise_removed_count") or 0),
        "native_hyphenation_repair_count": int(details.get("native_hyphenation_repair_count") or 0),
        "ocr_margin_noise_removed_count": sum(int(item.get("margin_noise_removed") or 0) for item in details.get("ocr_page_durations", [])),
        "ocr_spacing_repair_count": sum(int(item.get("spacing_repairs") or 0) for item in details.get("ocr_page_durations", [])),
        "mean_ocr_confidence": mean_ocr_confidence,
        "short_ocr_block_ratio": short_ocr_block_ratio,
        "replacement_character_rate": round(sum(page.get("replacement_character_rate", 0.0) for page in pages) / max(1, len(pages)), 6),
        "mojibake_rate": round(sum(page.get("mojibake_rate", 0.0) for page in pages) / max(1, len(pages)), 6),
        "cross_extractor_agreement": round(sum(agreements) / len(agreements), 4) if agreements else None,
        "reading_order_confidence": round(sum(page.get("reading_order_confidence", 0.0) for page in pages) / max(1, len(pages)), 4),
        "max_column_count": max((int(page.get("column_count") or 1) for page in pages), default=1),
        "multi_column_page_count": sum(int(page.get("column_count") or 1) > 1 for page in pages),
        "rotated_pages": [int(page["page"]) for page in pages if int(page.get("rotation") or 0) % 360 != 0],
        "section_coverage": coverage,
        "figure_caption_count": len(index.get("figures", [])),
        "table_caption_count": len(index.get("tables", [])),
        "section_count": len(index.get("sections", [])),
        "typographic_heading_count": sum((int(item.get("page") or 0), str(item.get("block_id") or "")) in bold_block_ids for item in index.get("sections", [])),
        "merged_heading_line_count": sum(len(item.get("continuation_block_ids", [])) for item in index.get("sections", [])),
        "poppler_available": details.get("poppler_available", False),
        "warnings": warnings,
        "elapsed_seconds": details.get("elapsed_seconds", 0.0),
    }


def parse_paper(
    path: str | Path,
    max_chars: int = 90000,
    deadline_at: float | None = None,
    ocr_engine: str = "off",
    ocr_lang: str = "en_ch",
    ocr_adapter: Callable | None = None,
    max_ocr_pages: int = 6,
    ocr_rescue_min_remaining: float = 45.0,
) -> dict[str, Any]:
    source = Path(path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Paper does not exist: {source}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source.suffix.lower() == ".pdf":
        pages, details = _read_pdf_pages(source, max_chars, deadline_at, ocr_engine, ocr_lang, ocr_adapter, max_ocr_pages, ocr_rescue_min_remaining)
        loader = "structured-pdf"
    else:
        pages, loader = _read_non_pdf_pages(source, max_chars)
        details = {"warnings": [], "ocr_candidate_pages": [], "ocr_pages": [], "poppler_available": False, "elapsed_seconds": 0.0}
    sections = _heading_candidates(pages)
    section_blocks = {
        (int(item.get("page") or 0), block_id)
        for item in sections
        for block_id in [str(item.get("block_id") or ""), *(str(value) for value in item.get("continuation_block_ids", []))]
        if block_id
    }
    for page in pages:
        for block in page.get("blocks", []):
            if (int(page["page"]), str(block.get("id") or "")) in section_blocks:
                block["kind"] = "heading"
    document_index = _document_index(pages, sections)
    evidence = _build_evidence(pages, sections, document_index, max_chars)
    all_text = "\n\n".join(page.get("text", "") for page in pages)
    extraction_report = _extraction_report(source, pages, document_index, details)
    evidence_pages = {int(item.get("page") or 0) for item in evidence if item.get("page")}
    extraction_report["evidence_char_count"] = sum(int(item.get("char_count") or 0) for item in evidence)
    extraction_report["evidence_page_count"] = len(evidence_pages)
    extraction_report["evidence_page_coverage_ratio"] = round(len(evidence_pages) / max(1, len(pages)), 4)
    return {
        "summary": "Paper parsed into a structured, page-aware evidence model.",
        "source_path": str(source),
        "source_name": source.name,
        "source_type": source.suffix.lower(),
        "source_sha256": source_hash,
        "loader": loader,
        "page_count": len(pages),
        "char_count": len(all_text),
        "headings": [item["title"] for item in sections],
        "sections": sections,
        "pages": pages,
        "document_index": document_index,
        "evidence": evidence,
        "extraction_report": extraction_report,
    }


def paper_markdown(parsed: dict[str, Any]) -> str:
    parts = []
    for page in parsed.get("pages", []):
        parts.append(f"<!-- page {page['page']} -->\n\n{page.get('text', '')}")
    return "\n\n".join(parts).strip() + "\n"


def evidence_excerpt(parsed: dict, max_chars: int = 58000) -> str:
    prioritized = sorted(
        parsed.get("evidence", []),
        key=lambda item: (
            0 if item.get("kind") == "caption" and re.match(r"^(figure|fig\.)\s*1\b", str(item.get("text") or ""), re.IGNORECASE) and re.search(r"\b(components?|overview|framework|architecture|pipeline)\b", str(item.get("text") or ""), re.IGNORECASE) else
            1 if item.get("kind") == "caption" and re.search(r"\b(overview|framework|architecture|pipeline)\b", str(item.get("text") or ""), re.IGNORECASE) else
            2 if item.get("kind") == "caption" and re.match(r"^(figure|fig\.)\s*1\b", str(item.get("text") or ""), re.IGNORECASE) else
            3 if item.get("kind") == "caption" else
            4 if any(term in str(item.get("section_hint") or "").casefold() for term in ("abstract", "introduction", "method", "approach", "architecture", "framework", "conclusion")) else 5,
            int(item.get("page") or 0),
            str(item.get("block_id") or ""),
        ),
    )
    lines: list[str] = []
    used = 0
    for item in prioritized:
        block = f"[{item['id']} | page {item['page']} | {item.get('section_hint') or 'unknown section'} | {item.get('block_id') or 'no block'}]\n{item['text']}"
        if used + len(block) > max_chars:
            continue
        lines.append(block)
        used += len(block)
    return "\n\n".join(lines)
