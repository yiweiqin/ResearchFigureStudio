from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Callable

from ..paper_to_image.analyzer import parse_paper
from ..utils import ensure_dir, write_json


def _save_document(document: Any, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(target))
    document.close()
    return target


def _native_two_column_fixture(target: Path) -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((45, 48), "Abstract", fontname="hebo", fontsize=13)
    page.insert_textbox((45, 68, 555, 125), "A deterministic two-column extraction benchmark with enough scientific text for parser quality gates.", fontsize=10)
    page.insert_text((45, 155), "2 Method", fontname="hebo", fontsize=13)
    page.insert_textbox((45, 185, 275, 260), "LEFT_TOP encoder evidence begins the method flow and establishes the input representation.", fontsize=10)
    page.insert_textbox((45, 300, 275, 375), "LEFT_BOTTOM decoder evidence follows the encoder in the left reading column.", fontsize=10)
    page.insert_textbox((325, 185, 555, 260), "RIGHT_TOP retrieval evidence belongs after the complete left column.", fontsize=10)
    page.insert_textbox((325, 300, 555, 375), "RIGHT_BOTTOM output evidence finishes the two-column reading order.", fontsize=10)
    page.insert_textbox((45, 430, 555, 485), "Figure 1: Overview of the encoder, decoder, retrieval module, and final output.", fontsize=10)
    page.insert_text((45, 540), "3 Conclusion", fontname="hebo", fontsize=13)
    page.insert_textbox((45, 560, 555, 620), "The benchmark concludes with a complete evidence-grounded pipeline.", fontsize=10)
    return _save_document(document, target)


def _bold_heading_fixture(target: Path) -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((45, 50), "Abstract", fontname="hebo", fontsize=12)
    page.insert_textbox((45, 70, 555, 130), "A paper with unnumbered bold sections validates typography-aware section recovery.", fontsize=10)
    page.insert_text((45, 175), "Model Architecture", fontname="hebo", fontsize=11)
    page.insert_textbox((45, 195, 555, 260), "The architecture contains an image encoder, a prompt encoder, and a mask decoder.", fontsize=10)
    page.insert_text((45, 305), "Encoder and Decoder Stacks", fontname="hebo", fontsize=10)
    page.insert_textbox((45, 325, 555, 390), "The encoder representation conditions the decoder before the final prediction.", fontsize=10)
    page.insert_text((45, 435), "Conclusion", fontname="hebo", fontsize=11)
    page.insert_textbox((45, 455, 555, 520), "Typography-based boundaries preserve the scientific section context.", fontsize=10)
    return _save_document(document, target)


def _rotated_fixture(target: Path) -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((45, 50), "Abstract", fontname="hebo", fontsize=12)
    page.insert_textbox((45, 75, 555, 145), "A rotated scientific page must retain displayed coordinates and readable text.", fontsize=10)
    page.insert_text((45, 190), "2 Method", fontname="hebo", fontsize=12)
    page.insert_textbox((45, 215, 555, 290), "The rotated encoder sends its representation to a decoder and final output.", fontsize=10)
    page.insert_textbox((45, 335, 555, 390), "Figure 1: Rotated architecture overview with encoder and decoder stages.", fontsize=10)
    page.set_rotation(90)
    return _save_document(document, target)


def _mixed_scan_fixture(target: Path) -> Path:
    import fitz

    scan_source = fitz.open()
    scan_page = scan_source.new_page(width=600, height=800)
    scan_page.insert_text((50, 65), "2 Method", fontname="hebo", fontsize=18)
    scan_page.insert_textbox((50, 105, 550, 190), "The scanned encoder passes evidence to the scanned decoder and output module.", fontsize=15)
    scan_page.insert_textbox((50, 245, 550, 330), "Figure 1: Scanned architecture overview with encoder decoder and output.", fontsize=15)
    pixmap = scan_page.get_pixmap(dpi=180, alpha=False)
    scan_png = pixmap.tobytes("png")
    scan_source.close()

    document = fitz.open()
    page1 = document.new_page(width=600, height=800)
    page1.insert_text((45, 50), "Abstract", fontname="hebo", fontsize=12)
    page1.insert_textbox((45, 75, 555, 155), "A mixed PDF combines native text with one scanned method page for local OCR fallback.", fontsize=10)
    page2 = document.new_page(width=600, height=800)
    page2.insert_image(page2.rect, stream=scan_png)
    page3 = document.new_page(width=600, height=800)
    page3.insert_text((45, 50), "3 Conclusion", fontname="hebo", fontsize=12)
    page3.insert_textbox((45, 75, 555, 155), "The mixed extraction path preserves native pages and recovers the scanned method evidence.", fontsize=10)
    return _save_document(document, target)


def _repeated_margin_fixture(target: Path) -> Path:
    import fitz

    document = fitz.open()
    sections = [
        ("Abstract", "A document encoder grounds paper evidence before framework generation."),
        ("2 Method", "The document encoder sends grounded entities to a relation decoder and final output."),
        ("3 Experiments", "Experiments measure entity recall, relation recall, and extraction latency."),
        ("4 Conclusion", "The system preserves evidence citations and editable scientific labels."),
    ]
    for page_number, (heading, body) in enumerate(sections, 1):
        page = document.new_page(width=600, height=800)
        page.insert_text((45, 25), "Proceedings of the Example Conference 2026", fontsize=8)
        page.insert_text((45, 785), f"Anonymous Paper 1234 | Page {page_number}", fontsize=8)
        page.insert_text((45, 70), heading, fontname="hebo", fontsize=12)
        page.insert_textbox((45, 95, 555, 220), body, fontsize=10)
    return _save_document(document, target)


def _fixture_ocr_adapter(image_path: Path, _lang: str) -> list[dict[str, Any]]:
    if "page_002" not in image_path.name:
        return []
    lines = [
        ("2 Method", 110),
        ("The scanned encoder passes evidence to the scanned decoder and output module.", 220),
        ("Figure 1: Scanned architecture overview with encoder decoder and output.", 420),
    ]
    return [
        {
            "text": text,
            "confidence": 0.99,
            "quad": [[90, top], [1240, top], [1240, top + 55], [90, top + 55]],
        }
        for text, top in lines
    ]


def _render_preview(source: Path, target: Path, page_index: int = 0) -> Path:
    import fitz

    document = fitz.open(str(source))
    try:
        pixmap = document[page_index].get_pixmap(dpi=110, alpha=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(target))
    finally:
        document.close()
    return target


def _check(name: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "actual": actual, "expected": expected}


def _run_case(
    case_id: str,
    fixture: Path,
    out_dir: Path,
    checks: Callable[[dict[str, Any]], list[dict[str, Any]]],
    *,
    ocr_engine: str = "off",
    ocr_adapter: Callable | None = None,
    preview_page: int = 0,
) -> dict[str, Any]:
    started = time.monotonic()
    parsed = parse_paper(fixture, ocr_engine=ocr_engine, ocr_adapter=ocr_adapter)
    elapsed = round(time.monotonic() - started, 4)
    case_dir = ensure_dir(out_dir / case_id)
    write_json(case_dir / "document_model.json", parsed)
    write_json(case_dir / "extraction_report.json", parsed.get("extraction_report", {}))
    preview = _render_preview(fixture, case_dir / f"preview_page_{preview_page + 1}.png", preview_page)
    assertions = checks(parsed)
    ocr_page_durations = parsed.get("extraction_report", {}).get("ocr_page_durations", [])
    result = {
        "case_id": case_id,
        "ok": all(item.get("passed") for item in assertions),
        "fixture": str(fixture),
        "preview": str(preview),
        "elapsed_seconds": elapsed,
        "pdf_type": parsed.get("extraction_report", {}).get("pdf_type"),
        "page_count": parsed.get("page_count"),
        "section_count": parsed.get("extraction_report", {}).get("section_count"),
        "figure_caption_count": parsed.get("extraction_report", {}).get("figure_caption_count"),
        "ocr_pages": parsed.get("extraction_report", {}).get("ocr_pages", []),
        "ocr_spacing_repair_count": parsed.get("extraction_report", {}).get("ocr_spacing_repair_count", 0),
        "ocr_page_durations": ocr_page_durations,
        "ocr_stage_seconds": {
            name: round(sum(float(item.get(name) or 0.0) for item in ocr_page_durations), 4)
            for name in ("render_seconds", "detection_seconds", "classification_seconds", "recognition_seconds", "postprocess_seconds", "inference_seconds")
        },
        "assertions": assertions,
    }
    write_json(case_dir / "benchmark_result.json", result)
    return result


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 4)


def run_pdf_extraction_stress_suite(out: str | Path, ocr_engine: str = "off") -> dict[str, Any]:
    root = ensure_dir(out).resolve()
    fixtures = ensure_dir(root / "fixtures")
    native = _native_two_column_fixture(fixtures / "native_two_column.pdf")
    bold = _bold_heading_fixture(fixtures / "unnumbered_bold_sections.pdf")
    rotated = _rotated_fixture(fixtures / "rotated_native_page.pdf")
    mixed = _mixed_scan_fixture(fixtures / "mixed_scan.pdf")
    repeated_margin = _repeated_margin_fixture(fixtures / "repeated_margin_noise.pdf")

    results = [
        _run_case(
            "native_two_column",
            native,
            root,
            lambda parsed: [
                _check("two_columns", parsed["extraction_report"].get("max_column_count") == 2, parsed["extraction_report"].get("max_column_count"), 2),
                _check("reading_order", all(parsed["pages"][0]["text"].index(left) < parsed["pages"][0]["text"].index(right) for left, right in (("LEFT_TOP", "LEFT_BOTTOM"), ("LEFT_BOTTOM", "RIGHT_TOP"), ("RIGHT_TOP", "RIGHT_BOTTOM"))), parsed["pages"][0]["text"], "LEFT_TOP < LEFT_BOTTOM < RIGHT_TOP < RIGHT_BOTTOM"),
                _check("cross_column_caption_order", parsed["pages"][0]["text"].index("RIGHT_BOTTOM") < parsed["pages"][0]["text"].index("Figure 1:") < parsed["pages"][0]["text"].index("3 Conclusion"), parsed["pages"][0]["text"], "RIGHT_BOTTOM < Figure 1 < Conclusion"),
                _check("figure_caption", parsed["extraction_report"].get("figure_caption_count", 0) >= 1, parsed["extraction_report"].get("figure_caption_count"), ">=1"),
                _check("priority_sections", all(parsed["extraction_report"].get("section_coverage", {}).get(name) for name in ("abstract", "method", "conclusion")), parsed["extraction_report"].get("section_coverage"), "abstract/method/conclusion"),
            ],
        ),
        _run_case(
            "unnumbered_bold_sections",
            bold,
            root,
            lambda parsed: [
                _check("model_architecture_heading", "Model Architecture" in parsed.get("headings", []), parsed.get("headings", []), "Model Architecture"),
                _check("stack_heading", "Encoder and Decoder Stacks" in parsed.get("headings", []), parsed.get("headings", []), "Encoder and Decoder Stacks"),
                _check("section_hint", any(item.get("section_hint") == "Model Architecture" and "image encoder" in str(item.get("text") or "").casefold() for item in parsed.get("evidence", [])), [item.get("section_hint") for item in parsed.get("evidence", []) if "image encoder" in str(item.get("text") or "").casefold()], "Model Architecture"),
            ],
        ),
        _run_case(
            "rotated_native_page",
            rotated,
            root,
            lambda parsed: [
                _check("rotation", parsed["extraction_report"].get("rotated_pages") == [1], parsed["extraction_report"].get("rotated_pages"), [1]),
                _check("display_coordinates", all(0 <= block["bbox"][0] <= block["bbox"][2] <= parsed["pages"][0]["width"] and 0 <= block["bbox"][1] <= block["bbox"][3] <= parsed["pages"][0]["height"] for block in parsed["pages"][0]["blocks"]), parsed["pages"][0]["blocks"], "all blocks inside displayed page"),
                _check("semantic_reading_order", parsed["pages"][0]["text"].index("Abstract") < parsed["pages"][0]["text"].index("2 Method") < parsed["pages"][0]["text"].index("Figure 1:"), parsed["pages"][0]["text"], "Abstract < Method < Figure 1"),
                _check("caption", parsed["extraction_report"].get("figure_caption_count", 0) >= 1, parsed["extraction_report"].get("figure_caption_count"), ">=1"),
            ],
        ),
        _run_case(
            "mixed_scan_fixture_adapter",
            mixed,
            root,
            lambda parsed: [
                _check("mixed_pdf", parsed["extraction_report"].get("pdf_type") == "mixed", parsed["extraction_report"].get("pdf_type"), "mixed"),
                _check("local_ocr", parsed["extraction_report"].get("ocr_pages") == [2], parsed["extraction_report"].get("ocr_pages"), [2]),
                _check("method_recovered", parsed["extraction_report"].get("section_coverage", {}).get("method") is True, parsed["extraction_report"].get("section_coverage"), "method=true"),
                _check("scanned_caption", any("Scanned architecture overview" in str(item.get("caption") or "") for item in parsed.get("document_index", {}).get("figures", [])), parsed.get("document_index", {}).get("figures", []), "scanned Figure 1 caption"),
            ],
            ocr_engine="easyocr",
            ocr_adapter=_fixture_ocr_adapter,
            preview_page=1,
        ),
        _run_case(
            "repeated_margin_noise",
            repeated_margin,
            root,
            lambda parsed: [
                _check("noise_removed", parsed["extraction_report"].get("repeated_margin_noise_removed_count") == 8, parsed["extraction_report"].get("repeated_margin_noise_removed_count"), 8),
                _check("header_absent", all("Proceedings of the Example Conference" not in item.get("text", "") for item in parsed.get("evidence", [])), [item.get("text") for item in parsed.get("evidence", [])], "no repeated header evidence"),
                _check("footer_absent", all("Anonymous Paper 1234" not in item.get("text", "") for item in parsed.get("evidence", [])), [item.get("text") for item in parsed.get("evidence", [])], "no repeated footer evidence"),
                _check("scientific_content_preserved", any("relation decoder" in item.get("text", "").casefold() for item in parsed.get("evidence", [])), [item.get("text") for item in parsed.get("evidence", [])], "relation decoder evidence"),
            ],
        ),
    ]

    if ocr_engine != "off":
        results.append(_run_case(
            "mixed_scan_runtime_ocr",
            mixed,
            root,
            lambda parsed: [
                _check("ocr_completed", 2 in parsed["extraction_report"].get("ocr_pages", []), parsed["extraction_report"].get("ocr_pages", []), "contains page 2"),
                _check("method_spacing", "2 method" in parsed["pages"][1].get("text", "").casefold(), parsed["pages"][1].get("text", ""), "contains '2 Method'"),
                _check("sentence_spacing", "scanned encoder passes evidence to the scanned decoder and output" in parsed["pages"][1].get("text", "").casefold(), parsed["pages"][1].get("text", ""), "spaced scientific sentence"),
                _check("caption_spacing", "scanned architecture overview with encoder decoder and output" in parsed["pages"][1].get("text", "").casefold(), parsed["pages"][1].get("text", ""), "spaced caption"),
                _check("repairs_recorded", parsed["extraction_report"].get("ocr_spacing_repair_count", 0) > 0, parsed["extraction_report"].get("ocr_spacing_repair_count", 0), ">0"),
            ],
            ocr_engine=ocr_engine,
            preview_page=1,
        ))

    elapsed = [float(item.get("elapsed_seconds") or 0.0) for item in results]
    ocr_stage_totals = {
        name: round(sum(float(item.get("ocr_stage_seconds", {}).get(name) or 0.0) for item in results), 4)
        for name in ("render_seconds", "detection_seconds", "classification_seconds", "recognition_seconds", "postprocess_seconds", "inference_seconds")
    }
    report = {
        "summary": "Deterministic multi-layout PDF extraction stress suite completed.",
        "ok": all(item.get("ok") for item in results),
        "out_dir": str(root),
        "ocr_engine": ocr_engine,
        "aggregate": {
            "case_count": len(results),
            "passed_case_count": sum(bool(item.get("ok")) for item in results),
            "mean_elapsed_seconds": round(sum(elapsed) / max(1, len(elapsed)), 4),
            "p95_elapsed_seconds": _percentile(elapsed, 0.95),
            "ocr_case_count": sum(bool(item.get("ocr_pages")) for item in results),
            "ocr_stage_seconds": ocr_stage_totals,
        },
        "cases": results,
    }
    write_json(root / "pdf_extraction_stress_report.json", report)
    return report
