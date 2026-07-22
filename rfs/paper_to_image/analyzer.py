from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable


MOJIBAKE_MARKERS = ("�", "Ã", "Â", "鈭", "鈥", "尾", "卤", "绗", "鍥", "琛")
SECTION_ALIASES = {
    "abstract": ("abstract",),
    "introduction": ("introduction", "background"),
    "method": ("method", "methods", "methodology", "approach", "architecture", "system overview", "framework"),
    "experiments": ("experiment", "experiments", "evaluation", "results"),
    "conclusion": ("conclusion", "conclusions", "discussion"),
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


def _normalized_compare_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(text).casefold())


def _replacement_rate(text: str) -> float:
    return round(text.count("�") / max(1, len(text)), 6)


def _mojibake_rate(text: str) -> float:
    return round(sum(text.count(marker) for marker in MOJIBAKE_MARKERS) / max(1, len(text)), 6)


def _block_kind(text: str, width_ratio: float = 0.0) -> str:
    value = _clean(text)
    if re.match(r"^(figure|fig\.|table)\s*[a-z0-9]+", value, re.IGNORECASE):
        return "caption" if value.casefold().startswith(("figure", "fig.")) else "table"
    if re.match(r"^(abstract|\d+(?:\.\d+)*\s+|[ivx]+[.)]\s+)(.{2,100})$", value, re.IGNORECASE) and len(value) <= 140:
        return "heading"
    if len(value) <= 180 and width_ratio >= 0.55 and not value.endswith((".", ",", ";")):
        return "title"
    if re.search(r"(?:[A-Za-z][A-Za-z0-9_{}^\-]*\s*=\s*[^=\n]{3,}|∑|∫|≤|≥|≈)", value):
        return "formula"
    return "paragraph"


def _reading_order(blocks: list[dict[str, Any]], page_width: float) -> tuple[list[dict[str, Any]], float]:
    if not blocks:
        return [], 0.0
    usable = [item for item in blocks if _clean(item.get("text", ""))]
    if not usable:
        return [], 0.0
    midpoint = page_width / 2.0
    spanning = [item for item in usable if float(item["bbox"][2]) - float(item["bbox"][0]) >= page_width * 0.62]
    left = [item for item in usable if item not in spanning and (float(item["bbox"][0]) + float(item["bbox"][2])) / 2 <= midpoint]
    right = [item for item in usable if item not in spanning and item not in left]
    two_column = len(left) >= 2 and len(right) >= 2
    if not two_column:
        ordered = sorted(usable, key=lambda item: (round(float(item["bbox"][1]), 1), float(item["bbox"][0])))
        confidence = 0.96
    else:
        boundaries = sorted(spanning, key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0])))
        ordered = []
        cursor = float("-inf")
        for boundary in boundaries + [None]:
            limit = float(boundary["bbox"][1]) if boundary else float("inf")
            segment = [item for item in usable if item not in spanning and cursor <= float(item["bbox"][1]) < limit]
            ordered.extend(sorted((item for item in segment if item in left), key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0]))))
            ordered.extend(sorted((item for item in segment if item in right), key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0]))))
            if boundary:
                ordered.append(boundary)
                cursor = float(boundary["bbox"][3])
        seen: set[int] = set()
        ordered = [item for item in ordered if not (id(item) in seen or seen.add(id(item)))]
        confidence = 0.88 if spanning else 0.82
    for index, item in enumerate(ordered, 1):
        item["reading_order"] = index
    return ordered, confidence


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
            records.append({"bbox": bbox, "text": text, "source": "pymupdf", "confidence": 1.0, "parent_block": parent_index})
    return records


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


def _ocr_records(image_path: Path, engine: str, lang: str, adapter: Callable | None) -> tuple[list[dict[str, Any]], str]:
    if adapter:
        return list(adapter(image_path, lang) or []), "adapter"
    from ..reference_text_extractor import run_easyocr, run_paddle_ocr

    requested = engine
    if requested == "auto":
        requested = "easyocr"
        try:
            import easyocr  # noqa: F401
        except Exception:
            requested = "paddle"
    if requested == "easyocr":
        return run_easyocr(image_path, lang), "easyocr"
    if requested == "paddle":
        return run_paddle_ocr(image_path, lang), "paddle"
    return [], "off"


def _ocr_page(page: Any, page_number: int, engine: str, lang: str, adapter: Callable | None) -> tuple[list[dict[str, Any]], str, str | None]:
    try:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / f"page_{page_number:03d}.png"
            pixmap = page.get_pixmap(dpi=200, alpha=False)
            pixmap.save(str(target))
            records, used_engine = _ocr_records(target, engine, lang, adapter)
            blocks = []
            scale_x = float(page.rect.width) / max(1, pixmap.width)
            scale_y = float(page.rect.height) / max(1, pixmap.height)
            for record in records:
                quad = record.get("quad") or []
                if not quad:
                    continue
                xs = [float(point[0]) for point in quad]
                ys = [float(point[1]) for point in quad]
                blocks.append({
                    "bbox": [min(xs) * scale_x, min(ys) * scale_y, max(xs) * scale_x, max(ys) * scale_y],
                    "text": _clean(record.get("text", "")),
                    "source": used_engine,
                    "confidence": round(float(record.get("confidence") or 0.0), 4),
                })
            return blocks, used_engine, None
    except Exception as exc:
        return [], engine, str(exc)


def _read_pdf_pages(
    path: Path,
    max_chars: int,
    deadline_at: float | None,
    ocr_engine: str,
    ocr_lang: str,
    ocr_adapter: Callable | None,
    max_ocr_pages: int,
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
            raw_blocks = _pymupdf_line_blocks(page)
            ordered, order_confidence = _reading_order(raw_blocks, float(page.rect.width))
            if len(_normalized_compare_text(" ".join(item["text"] for item in ordered))) < 80:
                fallback_blocks = _pdfplumber_blocks(path, index)
                fallback_ordered, fallback_confidence = _reading_order(fallback_blocks, float(page.rect.width))
                if len(_normalized_compare_text(" ".join(item["text"] for item in fallback_ordered))) > len(_normalized_compare_text(" ".join(item["text"] for item in ordered))):
                    ordered, order_confidence = fallback_ordered, min(fallback_confidence, 0.9)
            for block_index, block in enumerate(ordered, 1):
                block["id"] = f"P{index:03d}_B{block_index:03d}"
                block["kind"] = _block_kind(block["text"], (block["bbox"][2] - block["bbox"][0]) / max(1.0, float(page.rect.width)))
            page_text = "\n\n".join(item["text"] for item in ordered)
            poppler_page = poppler_text[index - 1] if index - 1 < len(poppler_text) else ""
            native_norm = _normalized_compare_text(page_text)
            poppler_norm = _normalized_compare_text(poppler_page)
            agreement = round(SequenceMatcher(None, native_norm[:20000], poppler_norm[:20000]).ratio(), 4) if native_norm and poppler_norm else None
            abnormal = len(native_norm) < 80 or _replacement_rate(page_text) > 0.005 or _mojibake_rate(page_text) > 0.005 or (agreement is not None and agreement < 0.35)
            if abnormal:
                ocr_candidates.append(index)
            pages.append({
                "page": index,
                "width": round(float(page.rect.width), 3),
                "height": round(float(page.rect.height), 3),
                "blocks": ordered,
                "text": page_text,
                "char_count": len(page_text),
                "replacement_character_rate": _replacement_rate(page_text),
                "mojibake_rate": _mojibake_rate(page_text),
                "poppler_agreement": agreement,
                "reading_order_confidence": order_confidence,
                "used_ocr": False,
            })
            used_chars += len(page_text)
            if used_chars >= max_chars and "max_chars reached; remaining pages retain metadata but not full evidence text" not in warnings:
                warnings.append("max_chars reached; remaining pages retain metadata but not full evidence text")
    finally:
        pass

    ocr_pages: list[int] = []
    if ocr_engine != "off":
        prioritized = ocr_candidates[:max_ocr_pages]
        for page_number in prioritized:
            if deadline_at is not None and time.monotonic() >= deadline_at - 20:
                warnings.append("OCR stopped to preserve deadline validation budget")
                break
            page = document[page_number - 1]
            blocks, used_engine, error = _ocr_page(page, page_number, ocr_engine, ocr_lang, ocr_adapter)
            if error:
                warnings.append(f"page {page_number} OCR unavailable: {error}")
                continue
            ordered, order_confidence = _reading_order(blocks, float(page.rect.width))
            for block_index, block in enumerate(ordered, 1):
                block["id"] = f"P{page_number:03d}_B{block_index:03d}"
                block["kind"] = _block_kind(block["text"], (block["bbox"][2] - block["bbox"][0]) / max(1.0, float(page.rect.width)))
            ocr_text = "\n\n".join(item["text"] for item in ordered)
            current = pages[page_number - 1]
            if len(_normalized_compare_text(ocr_text)) > len(_normalized_compare_text(current["text"])):
                current.update({
                    "blocks": ordered,
                    "text": ocr_text,
                    "char_count": len(ocr_text),
                    "replacement_character_rate": _replacement_rate(ocr_text),
                    "mojibake_rate": _mojibake_rate(ocr_text),
                    "reading_order_confidence": order_confidence,
                    "used_ocr": True,
                    "ocr_engine": used_engine,
                })
                ocr_pages.append(page_number)
    document.close()
    elapsed = round(time.monotonic() - started, 3)
    return pages, {
        "metadata": metadata,
        "ocr_candidate_pages": ocr_candidates,
        "ocr_pages": ocr_pages,
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
    for page in pages:
        for block in page.get("blocks", []):
            lines = [_clean(value) for value in str(block.get("text", "")).splitlines() if _clean(value)]
            for line_index, line in enumerate(lines):
                if not 2 <= len(line) <= 140:
                    continue
                explicit = re.match(r"^(abstract|references|acknowledg(?:e)?ments?|appendix)$", line, re.IGNORECASE)
                numbered = re.match(r"^\s*((?:\d+(?:\.\d+)*)|(?:[ivx]+))[.)]?\s+(.{2,120})$", line, re.IGNORECASE)
                compact_line = re.sub(r"[^a-z]", "", line.casefold())
                known = len(line) <= 60 and not line.endswith((".", ",", ";")) and any(compact_line.startswith(re.sub(r"[^a-z]", "", alias.casefold())) for aliases in SECTION_ALIASES.values() for alias in aliases)
                if numbered:
                    title_candidate = numbered.group(2).strip()
                    first_alpha = next((char for char in title_candidate if char.isalpha()), "")
                    if not first_alpha or not first_alpha.isupper() or re.search(r"[=±∑∫]", title_candidate) or title_candidate.endswith(".") or len(title_candidate) > 80 or len(title_candidate.split()) > 10:
                        numbered = None
                if not (explicit or numbered or known):
                    continue
                normalized = numbered.group(2).strip() if numbered else line.strip()
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    headings.append({"id": f"section_{len(headings) + 1:03d}", "title": normalized, "page": page["page"], "block_id": block["id"], "line_index": line_index})
    return headings[:80]


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
                    if parent is None or following.get("parent_block") != parent or re.match(r"^(figure|fig\.|table)\s*\d", str(following.get("text") or ""), re.IGNORECASE):
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
    compact = re.sub(r"[^a-z]", "", candidates)
    return {
        name: any(re.search(rf"\b{re.escape(alias)}\b", candidates) or re.sub(r"[^a-z]", "", alias.casefold()) in compact for alias in aliases)
        for name, aliases in SECTION_ALIASES.items()
    }


def _evidence_id(page: int, text: str, bbox: Any, kind: str) -> str:
    payload = json.dumps({"page": page, "text": _clean(text), "bbox": bbox, "kind": kind}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"E_P{int(page):03d}_{hashlib.sha1(payload).hexdigest()[:12]}"


def _build_evidence(pages: list[dict[str, Any]], sections: list[dict[str, Any]], document_index: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    section_positions = sorted(sections, key=lambda item: (item["page"], item.get("block_id", "")))
    evidence = []
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
    for page in pages:
        for block in page.get("blocks", []):
            text = _clean(block.get("text", ""))
            if not text or used >= max_chars:
                continue
            text = text[: max(0, max_chars - used)]
            section = next((item["title"] for item in reversed(section_positions) if item["page"] <= page["page"]), None)
            evidence.append({
                "id": _evidence_id(int(page["page"]), text, block.get("bbox"), str(block.get("kind") or "paragraph")),
                "page": page["page"],
                "block_id": block.get("id"),
                "bbox": block.get("bbox"),
                "section_hint": section,
                "kind": block.get("kind"),
                "source": block.get("source"),
                "confidence": block.get("confidence", 1.0),
                "text": text,
                "char_count": len(text),
            })
            used += len(text)
    for index, item in enumerate(evidence, 1):
        item["legacy_id"] = f"E{index:04d}"
    return evidence


def _extraction_report(source: Path, pages: list[dict[str, Any]], index: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    readable = [page for page in pages if len(_normalized_compare_text(page.get("text", ""))) >= 80]
    readable_ratio = round(len(readable) / max(1, len(pages)), 4)
    ocr_count = sum(1 for page in pages if page.get("used_ocr"))
    pdf_type = "mixed" if ocr_count and ocr_count < len(pages) else "scanned" if ocr_count else "born_digital"
    coverage = _section_coverage(pages, index.get("sections", []))
    warnings = list(details.get("warnings", []))
    if readable_ratio < 0.6:
        warnings.append("fewer than 60% of pages contain reliable text")
    if not coverage.get("abstract") or not coverage.get("method"):
        warnings.append("abstract or method-like section was not confidently located")
    agreements = [page["poppler_agreement"] for page in pages if isinstance(page.get("poppler_agreement"), (int, float))]
    report_status = "fail" if readable_ratio < 0.6 else "warning" if warnings else "pass"
    return {
        "summary": "PDF extraction quality and fallback report.",
        "status": report_status,
        "source_path": str(source),
        "pdf_type": pdf_type,
        "page_count": len(pages),
        "readable_page_count": len(readable),
        "readable_page_ratio": readable_ratio,
        "empty_or_low_text_pages": [page["page"] for page in pages if page not in readable],
        "ocr_candidate_pages": details.get("ocr_candidate_pages", []),
        "ocr_pages": details.get("ocr_pages", []),
        "replacement_character_rate": round(sum(page.get("replacement_character_rate", 0.0) for page in pages) / max(1, len(pages)), 6),
        "mojibake_rate": round(sum(page.get("mojibake_rate", 0.0) for page in pages) / max(1, len(pages)), 6),
        "cross_extractor_agreement": round(sum(agreements) / len(agreements), 4) if agreements else None,
        "reading_order_confidence": round(sum(page.get("reading_order_confidence", 0.0) for page in pages) / max(1, len(pages)), 4),
        "section_coverage": coverage,
        "figure_caption_count": len(index.get("figures", [])),
        "table_caption_count": len(index.get("tables", [])),
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
) -> dict[str, Any]:
    source = Path(path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Paper does not exist: {source}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source.suffix.lower() == ".pdf":
        pages, details = _read_pdf_pages(source, max_chars, deadline_at, ocr_engine, ocr_lang, ocr_adapter, max_ocr_pages)
        loader = "structured-pdf"
    else:
        pages, loader = _read_non_pdf_pages(source, max_chars)
        details = {"warnings": [], "ocr_candidate_pages": [], "ocr_pages": [], "poppler_available": False, "elapsed_seconds": 0.0}
    sections = _heading_candidates(pages)
    document_index = _document_index(pages, sections)
    evidence = _build_evidence(pages, sections, document_index, max_chars)
    all_text = "\n\n".join(page.get("text", "") for page in pages)
    if not evidence:
        raise ValueError("No readable paper text was extracted")
    extraction_report = _extraction_report(source, pages, document_index, details)
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
