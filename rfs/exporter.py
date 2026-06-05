from __future__ import annotations

import os
from pathlib import Path


def _export_pdf_with_powerpoint(pptx_path: Path, pdf_path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        import win32com.client  # type: ignore
        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
        presentation = powerpoint.Presentations.Open(str(pptx_path), WithWindow=False)
        presentation.SaveAs(str(pdf_path), 32)
        presentation.Close()
        powerpoint.Quit()
        return pdf_path.exists()
    except Exception:
        return False


def _render_pdf_to_png(pdf_path: Path, png_path: Path, dpi: int = 600) -> bool:
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        page = doc.load_page(0)
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        pix.save(str(png_path))
        doc.close()
        return png_path.exists()
    except Exception:
        return False


def export_outputs(pptx_path: str | Path, out_dir: str | Path) -> dict:
    pptx = Path(pptx_path)
    out = Path(out_dir)
    review_pdf = out / "review.pdf"
    final_png = out / "final_600dpi.png"

    if not _export_pdf_with_powerpoint(pptx, review_pdf):
        return {"pdf": None, "png": None, "status": "pptx_only_export_failed"}

    png_ok = _render_pdf_to_png(review_pdf, final_png, dpi=600)
    return {"pdf": str(review_pdf) if review_pdf.exists() else None, "png": str(final_png) if png_ok else None, "status": "ok" if png_ok else "pdf_only"}
