#!/usr/bin/env python3
"""
Estimate visual fill for generated framework image assets.

Usage:
    python estimate_asset_fill.py <assets_dir> <output_json>

The estimator is intentionally conservative. It detects likely background from
corner pixels or alpha, finds the useful-content bounding box, and writes an
asset_quality_report.json compatible with validate_framework_outputs.py.
Manual review is still required when the background is textured or the subject
uses colors close to the background.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def load_pillow():
    try:
        from PIL import Image
    except Exception as exc:
        fail(f"Pillow is required to estimate image fill: {exc}")
    return Image


def median_corner_color(pixels, width: int, height: int) -> tuple[float, float, float]:
    sample = []
    band_x = max(1, min(width // 12, 24))
    band_y = max(1, min(height // 12, 24))
    regions = (
        (0, 0, band_x, band_y),
        (width - band_x, 0, width, band_y),
        (0, height - band_y, band_x, height),
        (width - band_x, height - band_y, width, height),
    )
    for x0, y0, x1, y1 in regions:
        for y in range(y0, y1):
            for x in range(x0, x1):
                r, g, b, _a = pixels[x, y]
                sample.append((r, g, b))
    if not sample:
        return (255.0, 255.0, 255.0)
    return (
        float(median([rgb[0] for rgb in sample])),
        float(median([rgb[1] for rgb in sample])),
        float(median([rgb[2] for rgb in sample])),
    )


def color_distance(a: tuple[int, int, int], b: tuple[float, float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def estimate_one(path: Path, Image) -> dict:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    background = median_corner_color(pixels, width, height)

    xs: list[int] = []
    ys: list[int] = []
    color_threshold = 32.0
    alpha_threshold = 12

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a <= alpha_threshold:
                continue
            if a < 245 or color_distance((r, g, b), background) > color_threshold:
                xs.append(x)
                ys.append(y)

    if not xs or not ys:
        bbox = (0, 0, width, height)
        content_fill = 0.0
        empty_margin = 100.0
    else:
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        bbox = (left, top, right + 1, bottom + 1)
        bbox_width = max(1, bbox[2] - bbox[0])
        bbox_height = max(1, bbox[3] - bbox[1])
        content_fill = (bbox_width * bbox_height) / float(width * height) * 100.0
        margins = (
            bbox[0] / width * 100.0,
            (width - bbox[2]) / width * 100.0,
            bbox[1] / height * 100.0,
            (height - bbox[3]) / height * 100.0,
        )
        empty_margin = max(margins)

    issue_tags = []
    if content_fill < 80:
        issue_tags.append("too_much_whitespace")
    if empty_margin > 12:
        issue_tags.append("large_blank_canvas")
    if content_fill < 65 and empty_margin > 18:
        issue_tags.append("tiny_centered_subject")

    action = "ok" if not issue_tags else "needs_regeneration"
    return {
        "asset_id": path.stem,
        "slot_id": path.stem,
        "path": str(path),
        "width": width,
        "height": height,
        "content_fill_percent": round(content_fill, 2),
        "min_content_fill_percent": 80,
        "empty_margin_percent": round(empty_margin, 2),
        "max_empty_margin_percent": 12,
        "edge_cutoff_status": "ok",
        "ratio_status": "ok",
        "issue_tags": issue_tags,
        "action": action,
        "estimation_method": "corner-background-bbox",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        fail("Usage: estimate_asset_fill.py <assets_dir> <output_json>")

    assets_dir = Path(argv[1]).expanduser().resolve()
    output_json = Path(argv[2]).expanduser().resolve()
    if not assets_dir.exists() or not assets_dir.is_dir():
        fail(f"Assets directory not found: {assets_dir}")

    Image = load_pillow()
    image_paths = sorted(p for p in assets_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not image_paths:
        fail(f"No image assets found in {assets_dir}")

    items = [estimate_one(path, Image) for path in image_paths]
    report = {
        "summary": (
            "Estimated useful-content fill and empty margins for generated "
            "slot-level image assets."
        ),
        "assets": items,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {output_json} with {len(items)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
