from __future__ import annotations

from pathlib import Path


def load_text(path: str | Path, max_chars: int = 60000) -> dict:
    p = Path(path)
    suffix = p.suffix.lower()
    text = ""
    loader = "plain"

    if suffix == ".pdf":
        loader = "pymupdf"
        try:
            import fitz
            doc = fitz.open(str(p))
            parts = []
            for page in doc:
                parts.append(page.get_text("text"))
                if sum(len(x) for x in parts) >= max_chars:
                    break
            doc.close()
            text = "\n".join(parts)
        except Exception as exc:
            text = f"[PDF extraction failed: {exc}]"
    elif suffix in {".md", ".txt", ".tex", ".log", ".csv"}:
        text = p.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".docx":
        loader = "python-docx"
        try:
            import docx
            document = docx.Document(str(p))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        except Exception as exc:
            text = f"[DOCX extraction failed: {exc}]"
    else:
        text = p.read_text(encoding="utf-8", errors="ignore")

    text = text[:max_chars]
    return {
        "path": str(p),
        "suffix": suffix,
        "loader": loader,
        "char_count": len(text),
        "text": text,
    }
