from __future__ import annotations

import shutil
from pathlib import Path

from .utils import ensure_dir, write_json


def archive_inputs(paper: str | Path, reference: str | Path, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    inputs = ensure_dir(out / "inputs")
    paper_path = Path(paper)
    reference_path = Path(reference)

    archived = {
        "summary": "Archived source inputs for reproducible figure generation.",
        "paper_original": str(paper_path),
        "reference_original": str(reference_path),
        "paper_archived": None,
        "reference_archived": None,
    }

    if paper_path.exists():
        target = inputs / f"paper{paper_path.suffix.lower() or '.txt'}"
        shutil.copyfile(paper_path, target)
        archived["paper_archived"] = str(target)
    if reference_path.exists():
        target = inputs / f"reference{reference_path.suffix.lower() or '.png'}"
        shutil.copyfile(reference_path, target)
        archived["reference_archived"] = str(target)

    write_json(out / "input_manifest.json", archived)
    return archived
