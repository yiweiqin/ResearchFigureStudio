import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from rfs.paper_to_image.analyzer import _assign_ocr_parent_blocks, _filter_ocr_margin_noise, _prioritize_ocr_candidates, _rapidocr_worker_count, _token_overlap_agreement, parse_paper
from rfs.paper_to_image.inspection import inspect_paper
from rfs.reference_text_extractor import _positive_ocr_setting


class PaperAnalyzerTests(unittest.TestCase):
    def _pdf(self, draw) -> Path:
        root = Path(tempfile.mkdtemp())
        target = root / "paper.pdf"
        document = fitz.open()
        page = document.new_page(width=600, height=800)
        draw(page)
        document.save(target)
        document.close()
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        return target

    def _multipage_pdf(self, page_texts: list[list[str]]) -> Path:
        root = Path(tempfile.mkdtemp())
        target = root / "paper.pdf"
        document = fitz.open()
        for blocks in page_texts:
            page = document.new_page(width=600, height=800)
            top = 50
            for text in blocks:
                page.insert_textbox((45, top, 555, top + 110), text, fontsize=10)
                top += 120
        document.save(target)
        document.close()
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        return target

    def test_structured_pdf_preserves_page_blocks_and_captions(self):
        def draw(page):
            page.insert_text((50, 60), "1 Introduction", fontsize=14)
            page.insert_textbox((50, 90, 550, 180), "A readable scientific paper paragraph with enough text for extraction quality checks.", fontsize=10)
            page.insert_textbox((50, 220, 550, 280), "Figure 1: Overview of the proposed framework.", fontsize=10)

        parsed = parse_paper(self._pdf(draw))

        self.assertEqual(parsed["page_count"], 1)
        self.assertTrue(parsed["source_sha256"])
        self.assertTrue(parsed["pages"][0]["blocks"])
        self.assertEqual(parsed["document_index"]["figures"][0]["page"], 1)
        self.assertIn("Introduction", parsed["headings"])
        self.assertTrue(all(item.get("block_id") for item in parsed["evidence"]))

    def test_multiline_figure_caption_is_combined_into_priority_evidence(self):
        def draw(page):
            page.insert_textbox((50, 80, 550, 150), "Figure 1: Three interconnected components: a promptable task,\na model, and a data engine for collecting a large dataset.", fontsize=10)
            page.insert_textbox((50, 180, 550, 250), "1 Introduction\nA sufficiently long introduction paragraph for quality validation.", fontsize=10)

        parsed = parse_paper(self._pdf(draw))

        caption = parsed["document_index"]["figures"][0]["caption"]
        self.assertIn("data engine", caption)
        self.assertTrue(any(item["kind"] == "caption" and "data engine" in item["text"] for item in parsed["evidence"]))

    def test_two_column_blocks_are_sorted_left_then_right(self):
        def draw(page):
            page.insert_textbox((330, 100, 560, 180), "RIGHT COLUMN SECOND with enough words to form a complete paragraph.", fontsize=10)
            page.insert_textbox((40, 100, 270, 180), "LEFT COLUMN FIRST with enough words to form a complete paragraph.", fontsize=10)
            page.insert_textbox((40, 40, 560, 75), "2 Method", fontsize=14)
            page.insert_textbox((330, 220, 560, 300), "RIGHT COLUMN FOURTH with enough words to form a complete paragraph.", fontsize=10)
            page.insert_textbox((40, 220, 270, 300), "LEFT COLUMN THIRD with enough words to form a complete paragraph.", fontsize=10)

        parsed = parse_paper(self._pdf(draw))
        text = parsed["pages"][0]["text"]

        self.assertLess(text.index("LEFT COLUMN FIRST"), text.index("LEFT COLUMN THIRD"))
        self.assertLess(text.index("LEFT COLUMN THIRD"), text.index("RIGHT COLUMN SECOND"))
        self.assertGreaterEqual(parsed["pages"][0]["reading_order_confidence"], 0.8)
        self.assertEqual(parsed["pages"][0]["column_count"], 2)

    def test_cross_extractor_token_agreement_ignores_column_order(self):
        native = "left column first passage left column second passage right column first passage"
        poppler = "left column first passage right column first passage left column second passage"

        self.assertEqual(_token_overlap_agreement(native, poppler), 1.0)

    def test_cross_extractor_token_agreement_ignores_equation_variable_layout(self):
        native = "The projected point gives the origin and direction. ax x z ay y z az bz."
        poppler = "The projected point gives the origin and direction. a x x/z a y y/z a z + b z."

        self.assertEqual(_token_overlap_agreement(native, poppler), 1.0)

    def test_cross_extractor_token_agreement_allows_poppler_hidden_text(self):
        native = "The network architecture contains an encoder and decoder."
        poppler = native + " hidden latex accessibility expansion with many additional formula tokens"

        self.assertEqual(_token_overlap_agreement(native, poppler), 1.0)

    def test_three_column_blocks_are_sorted_column_major(self):
        def draw(page):
            page.insert_textbox((400, 100, 560, 170), "COLUMN THREE TOP complete scientific paragraph.", fontsize=9)
            page.insert_textbox((220, 100, 380, 170), "COLUMN TWO TOP complete scientific paragraph.", fontsize=9)
            page.insert_textbox((40, 100, 200, 170), "COLUMN ONE TOP complete scientific paragraph.", fontsize=9)
            page.insert_textbox((400, 220, 560, 290), "COLUMN THREE BOTTOM complete scientific paragraph.", fontsize=9)
            page.insert_textbox((220, 220, 380, 290), "COLUMN TWO BOTTOM complete scientific paragraph.", fontsize=9)
            page.insert_textbox((40, 220, 200, 290), "COLUMN ONE BOTTOM complete scientific paragraph.", fontsize=9)
            page.insert_textbox((40, 40, 560, 75), "3 Method Architecture and System Overview Across Three Columns", fontsize=13)

        parsed = parse_paper(self._pdf(draw))
        text = parsed["pages"][0]["text"]

        self.assertLess(text.index("COLUMN ONE TOP"), text.index("COLUMN ONE BOTTOM"))
        self.assertLess(text.index("COLUMN ONE BOTTOM"), text.index("COLUMN TWO TOP"))
        self.assertLess(text.index("COLUMN TWO BOTTOM"), text.index("COLUMN THREE TOP"))
        self.assertEqual(parsed["pages"][0]["column_count"], 3)
        self.assertEqual(parsed["extraction_report"]["max_column_count"], 3)

    def test_rotated_page_uses_display_coordinate_space(self):
        def draw(page):
            page.insert_textbox((40, 40, 560, 85), "Rotated Paper Architecture Overview", fontsize=14)
            page.insert_textbox((40, 120, 270, 220), "First scientific block with enough evidence for extraction.", fontsize=10)
            page.insert_textbox((330, 120, 560, 220), "Second scientific block with enough evidence for extraction.", fontsize=10)
            page.set_rotation(90)

        parsed = parse_paper(self._pdf(draw))
        page = parsed["pages"][0]

        self.assertEqual(page["rotation"], 90)
        self.assertEqual((page["width"], page["height"]), (800.0, 600.0))
        self.assertTrue(all(0 <= block["bbox"][0] <= block["bbox"][2] <= page["width"] for block in page["blocks"]))
        self.assertTrue(all(0 <= block["bbox"][1] <= block["bbox"][3] <= page["height"] for block in page["blocks"]))
        self.assertEqual(parsed["extraction_report"]["rotated_pages"], [1])

    def test_unicode_normalization_keeps_math_symbols(self):
        def draw(page):
            page.insert_text((50, 60), "3 Method", fontsize=14)
            page.insert_textbox((50, 100, 550, 180), "Model accuracy is approximately 95 percent and beta parameters are preserved.", fontsize=10)

        parsed = parse_paper(self._pdf(draw))

        self.assertEqual(parsed["extraction_report"]["replacement_character_rate"], 0.0)
        self.assertEqual(parsed["extraction_report"]["mojibake_rate"], 0.0)

    def test_low_text_page_uses_local_ocr_adapter(self):
        path = self._pdf(lambda _page: None)

        parsed = parse_paper(
            path,
            ocr_engine="easyocr",
            ocr_adapter=lambda _image, _lang: [{
                "text": "Abstract Method Image Encoder produces the final representation with reliable evidence.",
                "confidence": 0.93,
                "quad": [[10, 10], [900, 10], [900, 80], [10, 80]],
            }],
        )

        self.assertEqual(parsed["extraction_report"]["ocr_pages"], [1])
        self.assertTrue(parsed["pages"][0]["used_ocr"])
        self.assertIn("Image Encoder", parsed["pages"][0]["text"])

    def test_cross_extractor_content_disagreement_still_triggers_ocr(self):
        path = self._pdf(lambda page: page.insert_textbox(
            (40, 80, 560, 220),
            "Abstract Method The native parser returns a sufficiently long but unsupported passage about an encoder and decoder.",
            fontsize=10,
        ))
        ocr_text = "Abstract Method The verified page contains an image encoder, transformer decoder, training objective, inference output, and complete scientific evidence for the recovered framework."
        with patch("rfs.paper_to_image.analyzer._poppler_pages", return_value=(["Completely unrelated alternate parser content about chemistry molecules and laboratory measurements."], None)):
            parsed = parse_paper(
                path,
                ocr_engine="easyocr",
                ocr_adapter=lambda _image, _lang: [{
                    "text": ocr_text,
                    "confidence": 0.96,
                    "quad": [[20, 20], [950, 20], [950, 120], [20, 120]],
                }],
            )

        self.assertEqual(parsed["extraction_report"]["ocr_candidate_pages"], [1])
        self.assertEqual(parsed["extraction_report"]["ocr_pages"], [1])
        self.assertIn("verified page", parsed["pages"][0]["text"])

    def test_empty_ocr_result_returns_failed_document_model_instead_of_raising(self):
        path = self._pdf(lambda _page: None)

        parsed = parse_paper(path, ocr_engine="easyocr", ocr_adapter=lambda _image, _lang: [])

        self.assertEqual(parsed["extraction_report"]["status"], "fail")
        self.assertEqual(parsed["evidence"], [])
        self.assertEqual(parsed["extraction_report"]["pdf_type"], "scanned")

    def test_ocr_lines_are_grouped_into_complete_figure_caption(self):
        path = self._pdf(lambda _page: None)
        records = [
            {"text": "Figure 1: Overview of the proposed framework.", "confidence": 0.95, "quad": [[40, 100], [560, 100], [560, 125], [40, 125]]},
            {"text": "The image encoder feeds a transformer decoder.", "confidence": 0.94, "quad": [[40, 130], [560, 130], [560, 155], [40, 155]]},
            {"text": "1 Introduction", "confidence": 0.98, "quad": [[40, 210], [250, 210], [250, 240], [40, 240]]},
            {"text": "A sufficiently long scientific paragraph provides reliable evidence for the method.", "confidence": 0.96, "quad": [[40, 250], [560, 250], [560, 275], [40, 275]]},
        ]

        parsed = parse_paper(path, ocr_engine="easyocr", ocr_adapter=lambda _image, _lang: records)

        self.assertEqual(parsed["document_index"]["figures"][0]["caption"], "Figure 1: Overview of the proposed framework. The image encoder feeds a transformer decoder.")
        self.assertGreater(parsed["extraction_report"]["mean_ocr_confidence"], 0.9)

    def test_rapidocr_caption_group_survives_sentence_boundaries(self):
        lines = [
            {"bbox": [40, 100, 560, 120], "text": "Fig. 1: Overview of the model.", "confidence": 0.98},
            {"bbox": [40, 124, 560, 144], "text": "The encoder produces features.", "confidence": 0.98},
            {"bbox": [40, 148, 560, 168], "text": "A decoder predicts the output.", "confidence": 0.98},
            {"bbox": [40, 210, 560, 230], "text": "We next describe the training objective.", "confidence": 0.98},
        ]

        grouped = _assign_ocr_parent_blocks(lines, 600)

        self.assertEqual({item["parent_block"] for item in grouped[:3]}, {1})
        self.assertNotEqual(grouped[2]["parent_block"], grouped[3]["parent_block"])

    def test_ocr_margin_filter_removes_vertical_watermark_fragments(self):
        records = [
            {"bbox": [130, 100 + index * 30, 730, 124 + index * 30], "text": f"Complete scientific body line number {index} with reliable method evidence."}
            for index in range(6)
        ]
        records.extend([
            {"bbox": [35, 120, 70, 190], "text": "May"},
            {"bbox": [38, 210, 68, 245], "text": "28"},
            {"bbox": [90, 400, 180, 425], "text": "CNN"},
        ])

        filtered, removed = _filter_ocr_margin_noise(records, 842)

        self.assertEqual(removed, 2)
        self.assertIn("CNN", [item["text"] for item in filtered])

    def test_ocr_margin_filter_removes_fragments_even_when_body_starts_left(self):
        records = [
            {"bbox": [70, 300 + index * 30, 770, 324 + index * 30], "text": f"Long body line {index} establishes the left boundary near the page margin."}
            for index in range(6)
        ]
        records.extend([
            {"bbox": [35, 120, 70, 190], "text": "May"},
            {"bbox": [40, 220, 66, 246], "text": "S"},
            {"bbox": [63, 40, 790, 75], "text": "End-to-End Object Detection with Transformers"},
        ])

        filtered, removed = _filter_ocr_margin_noise(records, 842)

        self.assertEqual(removed, 2)
        self.assertIn("End-to-End Object Detection with Transformers", [item["text"] for item in filtered])

    def test_inspection_reuses_matching_document_cache(self):
        path = self._pdf(lambda page: page.insert_textbox((40, 80, 560, 180), "Abstract Method A sufficiently long scientific paragraph for deterministic PDF inspection.", fontsize=10))
        with tempfile.TemporaryDirectory() as temp:
            first = inspect_paper(path, temp, ocr_engine="off")
            second = inspect_paper(path, temp, ocr_engine="off")

            self.assertTrue(first["document_model"])
            self.assertEqual(second["status"], "cached")

    def test_global_document_cache_reuses_parse_across_output_directories(self):
        path = self._pdf(lambda page: page.insert_textbox((40, 80, 560, 220), "Abstract Method A sufficiently long scientific paragraph for global cache validation. The document contains repeated evidence, page-aware terminology, a complete method description, and enough characters to satisfy the readable-page quality gate.", fontsize=10))
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as first_out, tempfile.TemporaryDirectory() as second_out, patch.dict("os.environ", {"RFS_CACHE_DIR": cache}, clear=False):
            first = inspect_paper(path, first_out, ocr_engine="off")
            second = inspect_paper(path, second_out, ocr_engine="off")

            self.assertFalse(first["document_cache_hit"])
            self.assertTrue(second["document_cache_hit"])

    def test_evidence_ids_are_stable_across_repeated_parses(self):
        path = self._pdf(lambda page: page.insert_textbox((40, 80, 560, 180), "1 Method\nA stable block of scientific evidence for repeated parsing.", fontsize=10))

        first = parse_paper(path)
        second = parse_paper(path)

        self.assertEqual([item["id"] for item in first["evidence"]], [item["id"] for item in second["evidence"]])
        self.assertTrue(all(item["id"].startswith("E_P") for item in first["evidence"]))

    def test_evidence_budget_preserves_late_document_coverage(self):
        path = self._multipage_pdf([
            ["Abstract", "Early context " * 90],
            ["1 Introduction", "Our data engine has three stages:", "assisted-manual, semi-automatic, and fully automatic.", "Introduction evidence " * 24],
            ["2 Method", "The encoder transforms inputs into representations. " * 18],
            ["3 Experiments", "Experimental settings and evaluation metrics. " * 18],
            ["4 Analysis", "Ablation and error analysis evidence. " * 18],
            ["5 Conclusion", "The proposed method improves the final prediction while preserving scientific evidence. " * 12],
        ])

        parsed = parse_paper(path, max_chars=1800)
        evidence_pages = {item["page"] for item in parsed["evidence"]}

        self.assertEqual(evidence_pages, {1, 2, 3, 4, 5, 6})
        self.assertTrue(any(item["page"] == 6 and "Conclusion" in item["text"] for item in parsed["evidence"]))
        self.assertTrue(any("three stages" in item["text"] for item in parsed["evidence"]))
        self.assertTrue(any("assisted-manual" in item["text"] for item in parsed["evidence"]))
        self.assertEqual(parsed["extraction_report"]["evidence_page_coverage_ratio"], 1.0)
        self.assertLessEqual(parsed["extraction_report"]["evidence_char_count"], 1800)

    def test_ocr_priority_spreads_fully_scanned_long_document(self):
        pages = [{"page": index, "text": ""} for index in range(1, 13)]

        selected, details = _prioritize_ocr_candidates(pages, list(range(1, 13)), 6)

        self.assertEqual(selected, [1, 2, 3, 6, 9, 10])
        self.assertEqual([item["rank"] for item in details], [1, 2, 3, 4, 5, 6])

    def test_rapidocr_worker_count_is_bounded_and_adapter_safe(self):
        with patch.dict("os.environ", {"RFS_OCR_WORKERS": "3"}, clear=False):
            self.assertEqual(_rapidocr_worker_count("rapidocr", None, 6), min(3, __import__("os").cpu_count() or 1))
            self.assertEqual(_rapidocr_worker_count("rapidocr", lambda *_args: [], 6), 1)
            self.assertEqual(_rapidocr_worker_count("easyocr", None, 6), 1)

    def test_invalid_rapidocr_environment_setting_falls_back(self):
        with patch.dict("os.environ", {"RFS_RAPIDOCR_THREADS": "invalid"}, clear=False):
            self.assertEqual(_positive_ocr_setting(None, "RFS_RAPIDOCR_THREADS", 1), 1)

    def test_ocr_priority_prefers_semantic_pages_before_coverage_anchors(self):
        pages = [{"page": index, "text": ""} for index in range(1, 11)]
        pages[3]["text"] = "Figure 1: Overview of the proposed architecture and system pipeline."
        pages[7]["text"] = "8 Conclusion We summarize the method and its limitations."

        selected, details = _prioritize_ocr_candidates(pages, [1, 4, 6, 8, 10], 3)

        self.assertEqual(selected[:2], [4, 8])
        self.assertIn("overview_figure", details[0]["reasons"])
        self.assertIn("conclusion", details[1]["reasons"])

    def test_scanned_pdf_report_records_adaptive_ocr_schedule(self):
        path = self._multipage_pdf([[] for _ in range(12)])

        def adapter(image_path, _lang):
            page_number = int(Path(image_path).stem.rsplit("_", 1)[-1])
            return [{
                "text": f"Page {page_number} Abstract Method architecture evidence with enough reliable text for adaptive OCR scheduling and document recovery.",
                "confidence": 0.97,
                "quad": [[20, 20], [560, 20], [560, 70], [20, 70]],
            }]

        parsed = parse_paper(path, ocr_engine="easyocr", ocr_adapter=adapter, max_ocr_pages=6)

        self.assertEqual(parsed["extraction_report"]["ocr_priority_pages"], [1, 2, 3, 6, 9, 10])
        self.assertEqual(parsed["extraction_report"]["ocr_pages"], [1, 2, 3, 6, 9, 10])
        self.assertEqual([item["page"] for item in parsed["extraction_report"]["ocr_priority"]], [1, 2, 3, 6, 9, 10])
        self.assertEqual(parsed["extraction_report"]["status"], "warning")
        self.assertEqual(parsed["extraction_report"]["pdf_type"], "scanned")
        self.assertEqual(parsed["extraction_report"]["semantic_scope"], "sampled_pages_only")
        self.assertFalse(parsed["extraction_report"]["scientific_scope_complete"])


if __name__ == "__main__":
    unittest.main()
