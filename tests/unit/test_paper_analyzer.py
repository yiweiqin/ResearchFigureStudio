import tempfile
import unittest
from pathlib import Path

import fitz

from rfs.paper_to_image.analyzer import parse_paper
from rfs.paper_to_image.inspection import inspect_paper


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

    def test_inspection_reuses_matching_document_cache(self):
        path = self._pdf(lambda page: page.insert_textbox((40, 80, 560, 180), "Abstract Method A sufficiently long scientific paragraph for deterministic PDF inspection.", fontsize=10))
        with tempfile.TemporaryDirectory() as temp:
            first = inspect_paper(path, temp, ocr_engine="off")
            second = inspect_paper(path, temp, ocr_engine="off")

            self.assertTrue(first["document_model"])
            self.assertEqual(second["status"], "cached")


if __name__ == "__main__":
    unittest.main()
