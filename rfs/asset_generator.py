from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
import shutil
import time
from pathlib import Path
from statistics import median
from typing import Iterable

import requests
from PIL import Image, ImageDraw, ImageFont

from .utils import ensure_dir, write_json, write_text

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

CANDIDATE_DIRECTIONS = [
    "dense mechanism-first scientific mini scene with foreground, secondary objects, and micro-detail",
    "reference-crop reconstruction with layered local objects and edge-to-edge support detail",
    "compact paper-figure mini panel with concrete objects, internal mechanism, and background cues",
    "structured process card with visible before-and-after relation plus local reference texture",
    "high-density method card focused on the named operation, not a standalone pictogram",
]

NEGATIVE_PROMPT = (
    "Avoid: large empty margin, tiny centered object, sparse white background, isolated small icon on blank canvas, "
    "cropped subject, cut-off edges, fake formulas, fake axes, fake metrics, readable paragraphs, paper title text, "
    "watermarks, logos, screenshots, low-resolution blur, poster style, decorative clutter without scientific meaning, "
    "extra white presentation tile, white matting, large white border, generic blue-green dashboard styling, "
    "simple centered icon, single object on clean blank background, standalone pictogram."
)


def _parse_ratio(ratio: str) -> tuple[float, float]:
    try:
        left, right = ratio.split(":", 1)
        return max(0.001, float(left)), max(0.001, float(right))
    except Exception:
        return 1.0, 1.0


def _ratio_value(ratio: str) -> float:
    rw, rh = _parse_ratio(ratio)
    return rw / max(rh, 1)


def _target_size(ratio: str, max_side: int = 768, min_side: int = 96) -> tuple[int, int]:
    rw, rh = _parse_ratio(ratio)
    if rw >= rh:
        return max_side, max(min_side, int(max_side * rh / rw))
    return max(min_side, int(max_side * rw / rh)), max_side


def _as_list_text(value) -> str:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(items)
    return str(value or "").strip()


def _fallback_visual_metaphor(slot: dict) -> str:
    concept = str(slot.get("paper_concept", "scientific method component"))
    panel = str(slot.get("macro_panel") or slot.get("parent_panel") or "")
    low = f"{concept} {panel}".lower()
    if "sparse" in low or "nonzero" in low:
        return "draw a matrix grid with many pale empty cells and a few highlighted trainable nonzero cells"
    if "empty" in low or "zero" in low:
        return "draw a mostly empty matrix grid with muted zero cells and clear blank positions"
    if "frozen" in low or "pre-trained" in low or "pretrained" in low:
        return "draw a large locked frozen weight matrix slab, with icy muted cells and no trainable highlights"
    if "lora" in low:
        return "draw two slim low-rank matrix factors forming a compact adapter update beside a larger frozen weight matrix"
    if "ift" in low or "fourier" in low or "frequency" in low:
        return "draw a frequency-domain sparse grid transforming into a smooth spatial-domain matrix through wave arcs"
    if "split" in low or "submat" in low:
        return "draw one matrix split into multiple smaller aligned submatrices with visible separation cuts"
    if "concat" in low:
        return "draw multiple transformed matrix blocks stacked vertically into one taller concatenated matrix"
    if "adaptor" in low or "adapter" in low:
        return "draw a frozen shared projection block receiving matrix features and emitting a compact update"
    if "multiplication" in low:
        return "draw two matrix blocks combining through a multiplication junction into a compact output block"
    if "budget" in low or "parameter" in low:
        return "draw a tiny trainable budget highlighted against a large muted frozen parameter field"
    if "benchmark" in low or "evaluation" in low or "glue" in low:
        return "draw a benchmark suite board with multiple task tiles and abstract bars without readable numbers"
    return f"draw a concrete paper-specific visual object for {concept}, showing its role inside {panel}"


def build_slot_prompt(slot: dict, style: dict, candidate_index: int = 1) -> str:
    palette = ", ".join(style.get("palette", [])[:5])
    direction = CANDIDATE_DIRECTIONS[(candidate_index - 1) % len(CANDIDATE_DIRECTIONS)]
    composition = slot.get("composition_type", "full_frame_icon")
    visual_metaphor = str(slot.get("visual_metaphor") or "").strip() or _fallback_visual_metaphor(slot)
    slot_function = str(slot.get("slot_function") or "").strip()
    image_prompt_core = str(slot.get("image_prompt_core") or "").strip()
    reference_content_priority = str(slot.get("reference_content_priority") or "reference_primary_visual_object").strip()
    reference_visual_object = str(slot.get("reference_visual_object") or "").strip()
    reference_visual_elements = _as_list_text(slot.get("reference_visual_elements"))
    reference_color_palette = str(slot.get("reference_color_palette") or "").strip()
    paper_label_mapping = str(slot.get("paper_label_mapping") or "").strip()
    must_show = _as_list_text(slot.get("must_show")) or "the concrete scientific object, its internal structure, and its input-output relation"
    avoid_showing = _as_list_text(slot.get("avoid_showing")) or "generic sci-fi dashboard; unrelated robot or brain; fake formulas; fake numeric chart text"
    panel = str(slot.get("macro_panel") or slot.get("parent_panel") or "paper method")
    reference_slot_role = str(slot.get("reference_slot_role") or "slot in the user-provided reference layout").strip()
    reference_shape_language = str(slot.get("reference_shape_language") or slot.get("target_canvas_ratio") or "").strip()
    reference_local_style = str(slot.get("reference_local_style") or "match the reference figure's local card/icon discipline").strip()
    reference_prompt_hint = str(slot.get("reference_prompt_hint") or "use the reference image as local layout/style guidance, not as scientific content").strip()
    reference_crop_path = str(slot.get("reference_crop_path") or "").strip()
    reference_style_profile_path = str(slot.get("reference_style_profile_path") or "reference_style_profile.json").strip()
    local_color_token_ids = ", ".join(str(item) for item in slot.get("local_color_token_ids", []) if str(item).strip())
    complexity_kind = str(slot.get("complexity_kind") or "pipeline_module").strip()
    required_visual_complexity = str(slot.get("required_visual_complexity") or "dense").strip()
    foreground_subject = str(slot.get("foreground_subject") or reference_visual_object or visual_metaphor).strip()
    secondary_objects = _as_list_text(slot.get("secondary_objects")) or "2-5 supporting local objects from the reference crop"
    micro_details = _as_list_text(slot.get("micro_details")) or "small non-critical marks, separators, texture, and internal details"
    background_fill_elements = _as_list_text(slot.get("background_fill_elements")) or "edge-to-edge local reference-colored support detail"
    scientific_mechanism_detail = str(slot.get("scientific_mechanism_detail") or "show the paper concept as a visible mechanism, not a generic icon").strip()
    forbidden_simplification = _as_list_text(slot.get("forbidden_simplification")) or "simple icon; centered icon; clean blank background; single object on white canvas"
    is_simple_allowed = complexity_kind == "legend_icon"

    if composition == "scene_thumbnail":
        type_clause = (
            "Make it a dense small mechanism thumbnail: one concrete foreground scientific object, multiple visible process cues, secondary context objects, and enough environment to show what changes. Use edge-to-edge supporting scene detail so the crop is visually full."
        )
    elif composition == "full_bleed_card":
        type_clause = (
            "Make it a compact dense mechanism card: the central object fills the card, with internal subparts, small supporting objects, and micro process cues that clarify this exact operation. The card surface should extend almost to the image edge, with no separate white mat."
        )
    elif composition == "symbol_cutout":
        type_clause = (
            "Make it a large complete symbolic operation object plus local reference-colored support detail; the operation symbol or object should be visually distinct from other slots. If it is a line icon, thicken the strokes, enlarge it to nearly touch the safe area, and add compact supporting shapes so it is not sparse."
        )
    else:
        type_clause = (
            "Make it a full-frame scientific mechanism object with a large distinct subject, mechanism-specific internal details, and supporting local objects. If the subject is a waveform, face, pose skeleton, document, database, badge, or legend icon, make it bold, oversized, and backed by local reference-colored detail rather than a tiny object on a blank white field."
        )

    exact_ratio = float(slot.get("aspect_ratio_decimal") or _ratio_value(slot.get("target_canvas_ratio", "1.000:1.000")))
    center = slot.get("center_percent") if isinstance(slot.get("center_percent"), dict) else {}
    center_text = f"x={float(center.get('x', 0.5)):.3f}, y={float(center.get('y', 0.5)):.3f}"
    width_percent = float(slot.get("width_percent", slot.get("bbox_percent", {}).get("w", 0)))
    height_percent = float(slot.get("height_percent", slot.get("bbox_percent", {}).get("h", 0)))

    return (
        f"Create candidate {candidate_index} for one slot-level image block in a publication-quality AI/ML research framework figure. "
        f"This block belongs to macro panel: {panel}. Slot id: {slot['id']}. Paper concept: {slot['paper_concept']}. "
        f"Slot function: {slot_function or 'visualize this paper concept as one small editable figure asset'}. "
        f"Model-planned image prompt core: {image_prompt_core or visual_metaphor}. "
        f"Reference content priority: {reference_content_priority}. "
        f"Reference visual object to recreate: {reference_visual_object or visual_metaphor}. "
        f"Reference visual elements to preserve: {reference_visual_elements or must_show}. "
        f"Reference local color palette to preserve: {reference_color_palette or 'inherit colors from the local reference slot, not one global palette'}. "
        f"Reference style profile source: {reference_style_profile_path}. Local reference crop used by the prompt planner: {reference_crop_path or 'missing crop path - preserve described local crop anyway'}. "
        f"Local reference color token ids to inherit: {local_color_token_ids or 'none recorded; use local reference colors described in prompt plan'}. "
        f"Paper label mapping: {paper_label_mapping or 'paper terminology is added later as editable PPT text'}. "
        f"Main visual metaphor: {visual_metaphor}. "
        f"Must visibly show: {must_show}. "
        f"Reference-local slot role: {reference_slot_role}. "
        f"Reference shape language: {reference_shape_language}. "
        f"Reference-local style: {reference_local_style}. "
        f"Reference prompt hint: {reference_prompt_hint}. "
        f"Slot visual complexity contract: complexity_profile={slot.get('complexity_profile', 'reference-dense')}; complexity_kind={complexity_kind}; required_visual_complexity={required_visual_complexity}. "
        f"Foreground subject must be large: {foreground_subject}. "
        f"Secondary objects to include: {secondary_objects}. "
        f"Micro details to include: {micro_details}. "
        f"Background fill elements: {background_fill_elements}. "
        f"Scientific mechanism detail: {scientific_mechanism_detail}. "
        f"Forbidden simplifications: {forbidden_simplification}. "
        "Use the local reference slot object first; do not invent a different abstract paper-internal object when the reference shows a concrete object. "
        "The goal is to redraw/recreate the reference slot's object as a clean high-resolution asset, then adapt only minor details to the paper concept. "
        f"Reference geometry is mandatory: canvas aspect ratio = exact {exact_ratio:.3f}:1, target_canvas_ratio = {slot['target_canvas_ratio']}, "
        f"slot center in full figure = {center_text}, slot width_percent = {width_percent:.3f}, slot height_percent = {height_percent:.3f}. "
        "Generate this asset for the exact reference slot shape, not a generic preset ratio such as 1:1, 4:3, 3:4, 16:9, or 9:16. "
        "No semantic cropping: the whole subject must be visible, no object extending outside the frame, no cut-off hands/edges/bottom. "
        "Safe area means important subject remains complete inside the frame, but supporting background details should extend close to edges. "
        "Useful visual content should fill 90-97% of the canvas; minimum 85%; maximum empty margin is strictly below 10% on every edge. "
        "Use a full-frame composition, large subject, maximal detail density, rich scientific visual texture, minimal blank canvas, no tiny centered object. "
        + ("" if is_simple_allowed else "This must be a dense mini scientific scene/card with 2-5 layered objects, edge-to-edge supporting detail, and not a standalone pictogram. ")
        + "The subject plus its local reference-colored support surface should occupy almost the entire frame; avoid isolated cutout icons floating on white or transparent-looking empty space. "
        "For thin symbols such as pose skeletons, waveforms, clocks, microphones, documents, badges, and legend icons, use thick readable strokes, enlarged scale, and compact supporting shapes to raise visual fill while keeping the subject complete. "
        f"Candidate visual direction: {direction}. {type_clause} "
        f"Style constraints: polished academic paper illustration, crisp edges, consistent line quality, clean high-resolution vector-illustration / 2.5D hybrid only when useful. "
        f"Global palette may include {palette}, but local reference colors override the global palette. Preserve color variety across slots. "
        "Style consistency matters, but visual identity must vary by the reference crop: monitors look like monitors, video strips look like video strips, microphones look like microphones, waveforms look like waveforms, face cards look like face cards, pose skeletons look like pose skeletons, clocks look like clocks, clipboards look like clipboards, databases look like databases. "
        "Allow only very small decorative non-critical UI marks or blurred pseudo-labels. "
        "Critical scientific labels, formulas, variables, panel IDs, arrow labels, and metric values will be added later in PowerPoint and must not be generated in the image. "
        f"Do not show: {avoid_showing}. "
        "Do not add a white presentation tile, white mat, extra card background, or artificial border unless that exact border exists in the local reference crop. "
        f"{NEGATIVE_PROMPT}"
    )


def _draw_placeholder(slot: dict, path: Path, style: dict, candidate_index: int = 1) -> None:
    width, height = _target_size(slot["target_canvas_ratio"])
    palette = style.get("palette", ["#EAF5FF", "#DFF7EF", "#8EC9E8", "#66C6A4", "#163B4D"])
    bg = palette[(candidate_index - 1) % 2]
    line = palette[4] if len(palette) > 4 else "#163B4D"
    accent = palette[2 + ((candidate_index + len(slot["id"])) % max(1, min(2, len(palette) - 2)))] if len(palette) >= 4 else "#8EC9E8"
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    margin = max(8, int(min(width, height) * 0.035))
    draw.rounded_rectangle([margin, margin, width - margin, height - margin], radius=max(14, margin * 2), fill=bg, outline=line, width=max(3, margin // 4))

    # Dense edge-to-edge detail so placeholder QA exercises high-fill layouts.
    for i in range(8 + candidate_index):
        x = int(width * (0.035 + i * 0.12)) % width
        draw.line([x, margin, min(width - margin, x + int(width * 0.22)), height - margin], fill=accent, width=max(1, margin // 6))
    for i in range(6):
        y = int(height * (0.10 + i * 0.15))
        draw.arc([margin + i * 5, y, width - margin - i * 4, y + int(height * 0.26)], 180, 360, fill=accent, width=max(1, margin // 7))

    cx, cy = width // 2, height // 2
    main_w = int(width * (0.72 + 0.03 * ((candidate_index - 1) % 3)))
    main_h = int(height * (0.64 + 0.03 * ((candidate_index - 1) % 2)))
    kind = slot.get("composition_type", "full_frame_icon")
    if kind in {"scene_thumbnail", "full_bleed_card"}:
        draw.rounded_rectangle([cx - main_w // 2, cy - main_h // 2, cx + main_w // 2, cy + main_h // 2], radius=max(12, margin), fill="#FFFFFF", outline=line, width=max(3, margin // 4))
        panel_gap = max(4, margin // 3)
        for row in range(2):
            for col in range(2):
                px0 = cx - main_w // 2 + margin + col * ((main_w - margin * 2) // 2)
                py0 = cy - main_h // 2 + margin + row * ((main_h - margin * 2) // 2)
                px1 = px0 + (main_w - margin * 2) // 2 - panel_gap
                py1 = py0 + (main_h - margin * 2) // 2 - panel_gap
                draw.rounded_rectangle([px0, py0, px1, py1], radius=max(6, margin // 2), fill=accent if (row + col + candidate_index) % 2 == 0 else "#DFF7EF", outline=line, width=max(1, margin // 8))
                draw.polygon([(px0 + panel_gap, py1 - panel_gap), (px0 + (px1 - px0) // 2, py0 + panel_gap), (px1 - panel_gap, py1 - panel_gap)], fill="#9AD7C4")
    else:
        radius = min(main_w, main_h) // 2
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill="#FFFFFF", outline=line, width=max(4, margin // 3))
        for angle_idx in range(12):
            ang = angle_idx * math.pi / 6 + candidate_index * 0.08
            x1 = cx + int(math.cos(ang) * radius * 0.18)
            y1 = cy + int(math.sin(ang) * radius * 0.18)
            x2 = cx + int(math.cos(ang) * radius * 0.82)
            y2 = cy + int(math.sin(ang) * radius * 0.82)
            draw.line([x1, y1, x2, y2], fill=line, width=max(3, margin // 4))
            draw.ellipse([x2 - margin // 2, y2 - margin // 2, x2 + margin // 2, y2 + margin // 2], fill=accent, outline=line)
        inner = int(radius * 0.36)
        draw.rounded_rectangle([cx - inner, cy - inner, cx + inner, cy + inner], radius=max(8, margin // 2), fill=accent, outline=line, width=max(2, margin // 6))

    try:
        font = ImageFont.truetype("arial.ttf", max(9, int(min(width, height) * 0.045)))
    except Exception:
        font = ImageFont.load_default()
    draw.text((margin * 1.2, height - margin * 2.2), "UI", fill=line, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _supported_gemini_ratio(ratio: str) -> str:
    value = _ratio_value(ratio)
    supported = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "16:9": 16 / 9, "9:16": 9 / 16}
    return min(supported, key=lambda key: abs(supported[key] - value))


def _image2_model_name() -> str:
    model = os.getenv("RFS_IMAGE_MODEL") or os.getenv("IMAGE_MODEL") or "image-2"
    # Yunwu currently exposes GPT Image 2 under this model id. Keep "image-2"
    # as the user-facing logical name while sending the listed model id.
    if model == "image-2":
        return "gpt-image-2"
    return model


def _image2_size(ratio: str) -> str:
    value = _ratio_value(ratio)
    if value >= 1.25:
        return "1536x1024"
    if value <= 0.80:
        return "1024x1536"
    return "1024x1024"


def _write_image_response(data: dict, output_path: Path) -> bool:
    items = data.get("data") if isinstance(data.get("data"), list) else []
    if not items:
        return False
    item = items[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        output_path.write_bytes(base64.b64decode(item["b64_json"]))
        return True
    if item.get("url"):
        response = requests.get(item["url"], timeout=180)
        response.raise_for_status()
        output_path.write_bytes(response.content)
        return True
    return False


def _call_image2(prompt: str, ratio: str, output_path: Path, retries: int = 2) -> bool:
    api_base = os.getenv("API_BASE", "https://yunwu.ai/v1").rstrip("/")
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
    model = _image2_model_name()
    if not api_key:
        raise RuntimeError("API_KEY/GEMINI_API_KEY is required for --asset-mode image2")
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": _image2_size(ratio),
    }
    max_attempts = max(1, int(retries) + 1)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                f"{api_base}/images/generations",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=240,
            )
            if response.status_code == 400 and payload.get("size") != "1024x1024":
                # Some image gateways accept only square output for a model. The
                # prompt and final ratio-normalization still preserve slot ratio.
                payload = dict(payload)
                payload["size"] = "1024x1024"
                response = requests.post(
                    f"{api_base}/images/generations",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    data=json.dumps(payload),
                    timeout=240,
                )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                raise RuntimeError(f"image2 request returned HTTP {response.status_code}")
            response.raise_for_status()
            if _write_image_response(response.json(), output_path):
                return True
            raise RuntimeError("image2 response did not contain b64_json or url image data")
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            time.sleep(min(30.0, 2.0 * (2 ** (attempt - 1))))
    if last_error:
        raise last_error
    return False


def _call_gemini(prompt: str, ratio: str, output_path: Path, retries: int = 2) -> bool:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    url = os.getenv("GEMINI_GEN_IMG_URL")
    if not api_key or not url:
        raise RuntimeError("GEMINI_API_KEY/API_KEY and GEMINI_GEN_IMG_URL are required for --asset-mode gemini")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"imageSize": "2K", "aspectRatio": _supported_gemini_ratio(ratio)},
        },
    }
    max_attempts = max(1, int(retries) + 1)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=180,
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                raise RuntimeError(f"Gemini image request returned HTTP {response.status_code}")
            response.raise_for_status()
            data = response.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(base64.b64decode(inline["data"]))
                        return True
            raise RuntimeError("Gemini image response did not contain inline image data")
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            # Back off on rate limits, transient server errors, and network timeouts.
            time.sleep(min(30.0, 2.0 * (2 ** (attempt - 1))))
    if last_error:
        raise last_error
    return False


def _enforce_target_canvas_ratio(path: Path, ratio: str) -> None:
    """Resize to the exact slot canvas ratio without semantic cropping."""
    target_w, target_h = _target_size(ratio, max_side=1024, min_side=96)
    with Image.open(path) as image:
        converted = image.convert("RGBA")
        if converted.size == (target_w, target_h):
            return
        resized = converted.resize((target_w, target_h), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    resized.save(path)


def _content_bbox(rgba: Image.Image) -> tuple[list[int], float, float]:
    width, height = rgba.size
    pixels = rgba.load()
    background = _median_corner_color(pixels, width, height)
    xs: list[int] = []
    ys: list[int] = []
    color_threshold = 30.0
    alpha_threshold = 12
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a <= alpha_threshold:
                continue
            if a < 245 or _color_distance((r, g, b), background) > color_threshold:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return [0, 0, width, height], 0.0, 100.0
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    bbox_w = max(1, right - left + 1)
    bbox_h = max(1, bottom - top + 1)
    content_fill = bbox_w * bbox_h / float(width * height) * 100.0
    margins = (
        left / width * 100.0,
        (width - right - 1) / width * 100.0,
        top / height * 100.0,
        (height - bottom - 1) / height * 100.0,
    )
    return [left, top, right + 1, bottom + 1], content_fill, max(margins)


def _hex_rgb(value: str, fallback: tuple[int, int, int] = (229, 242, 248)) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) >= 6:
        try:
            return int(text[:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        except Exception:
            return fallback
    return fallback


def _fit_subject_to_canvas(path: Path, min_fill: float = 88.0, max_margin: float = 9.0, support_color: str | None = None) -> None:
    """Remove only plain background slack and enlarge the complete subject."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    width, height = rgba.size
    bbox, content_fill, empty_margin = _content_bbox(rgba)
    if content_fill >= min_fill and empty_margin <= max_margin:
        return
    left, top, right, bottom = bbox
    pad_x = max(4, int((right - left) * 0.06))
    pad_y = max(4, int((bottom - top) * 0.06))
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(width, right + pad_x)
    bottom = min(height, bottom + pad_y)
    if right <= left or bottom <= top:
        return
    subject = rgba.crop((left, top, right, bottom))
    scale = min(width * 0.94 / max(subject.width, 1), height * 0.94 / max(subject.height, 1))
    if scale <= 1.02:
        canvas = rgba
    else:
        new_w = max(1, min(width, int(subject.width * scale)))
        new_h = max(1, min(height, int(subject.height * scale)))
        subject = subject.resize((new_w, new_h), Image.LANCZOS)
        pixels = rgba.load()
        bg = tuple(int(v) for v in _median_corner_color(pixels, width, height)) + (255,)
        canvas = Image.new("RGBA", (width, height), bg)
        canvas.alpha_composite(subject, ((width - new_w) // 2, (height - new_h) // 2))
    _bbox, final_fill, final_margin = _content_bbox(canvas)
    if (final_fill < min_fill or final_margin > max_margin) and support_color:
        support = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(support)
        r, g, b = _hex_rgb(support_color)
        inset_x = max(2, int(width * 0.025))
        inset_y = max(2, int(height * 0.025))
        draw.rounded_rectangle(
            (inset_x, inset_y, width - inset_x, height - inset_y),
            radius=max(8, min(width, height) // 12),
            fill=(r, g, b, 82),
            outline=(r, g, b, 150),
            width=max(2, min(width, height) // 80),
        )
        for i in range(5):
            x = int(width * (0.10 + i * 0.18))
            draw.line((x, inset_y + 4, x + int(width * 0.10), height - inset_y - 4), fill=(r, g, b, 58), width=2)
        canvas.alpha_composite(support)
    canvas.save(path)


def _median_corner_color(pixels, width: int, height: int) -> tuple[float, float, float]:
    sample = []
    band_x = max(1, min(width // 12, 28))
    band_y = max(1, min(height // 12, 28))
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


def _color_distance(a: tuple[int, int, int], b: tuple[float, float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _estimate_quality(path: Path, slot: dict, candidate_index: int, source: str) -> dict:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    background = _median_corner_color(pixels, width, height)

    xs: list[int] = []
    ys: list[int] = []
    color_threshold = 30.0
    alpha_threshold = 12
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a <= alpha_threshold:
                continue
            if a < 245 or _color_distance((r, g, b), background) > color_threshold:
                xs.append(x)
                ys.append(y)

    if not xs or not ys:
        content_fill = 0.0
        empty_margin = 100.0
        bbox = [0, 0, width, height]
    else:
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        bbox_w = max(1, right - left + 1)
        bbox_h = max(1, bottom - top + 1)
        bbox = [left, top, right + 1, bottom + 1]
        content_fill = bbox_w * bbox_h / float(width * height) * 100.0
        margins = (
            left / width * 100.0,
            (width - right - 1) / width * 100.0,
            top / height * 100.0,
            (height - bottom - 1) / height * 100.0,
        )
        empty_margin = max(margins)

    image_ratio = width / max(height, 1)
    target_ratio = _ratio_value(slot["target_canvas_ratio"])
    ratio_mismatch_percent = abs(image_ratio - target_ratio) / max(target_ratio, 0.001) * 100.0

    issue_tags = []
    if content_fill < float(slot.get("min_content_fill_percent", 80)):
        issue_tags.append("too_much_whitespace")
    if empty_margin > float(slot.get("max_empty_margin_percent", 12)):
        issue_tags.append("large_blank_canvas")
    if content_fill < 65 and empty_margin > 18:
        issue_tags.append("tiny_centered_subject")
    if ratio_mismatch_percent > 10:
        issue_tags.append("ratio_mismatch")

    fill_score = min(content_fill, 95.0) - max(0.0, content_fill - 95.0) * 1.5
    margin_penalty = max(0.0, empty_margin - 12.0) * 4.0
    ratio_penalty = max(0.0, ratio_mismatch_percent - 10.0) * 2.0
    score = fill_score - margin_penalty - ratio_penalty

    return {
        "candidate_index": candidate_index,
        "path": str(path),
        "source": source,
        "width": width,
        "height": height,
        "content_bbox_px": bbox,
        "content_fill_percent": round(content_fill, 2),
        "min_content_fill_percent": slot["min_content_fill_percent"],
        "empty_margin_percent": round(empty_margin, 2),
        "max_empty_margin_percent": slot["max_empty_margin_percent"],
        "ratio_mismatch_percent": round(ratio_mismatch_percent, 2),
        "edge_cutoff_status": "ok",
        "ratio_status": "ok" if ratio_mismatch_percent <= 10 else "needs_ratio_regeneration",
        "issue_tags": issue_tags,
        "selection_score": round(score, 2),
        "action": "ok_no_crop" if not issue_tags else "candidate_rejected",
        "estimation_method": "corner-background-content-bbox",
    }


def _simple_allowed_slot(slot: dict) -> bool:
    text = " ".join(
        str(slot.get(key, ""))
        for key in ["id", "paper_concept", "macro_panel", "parent_panel", "complexity_kind", "composition_type"]
    ).lower()
    return str(slot.get("complexity_kind", "")).lower() == "legend_icon" or any(
        term in text
        for term in ["legend", "badge", "label", "ocean", "openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
    )


def _estimate_component_count(mask: list[list[bool]]) -> int:
    if not mask or not mask[0]:
        return 0
    height = len(mask)
    width = len(mask[0])
    seen = [[False] * width for _ in range(height)]
    components = 0
    min_area = max(6, int(width * height * 0.002))
    for y in range(height):
        for x in range(width):
            if seen[y][x] or not mask[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            area = 0
            while stack:
                px, py = stack.pop()
                area += 1
                for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                    if 0 <= nx < width and 0 <= ny < height and not seen[ny][nx] and mask[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if area >= min_area:
                components += 1
    return components


def _estimate_complexity(path: Path, slot: dict, quality: dict) -> dict:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    width, height = rgba.size
    small_w = 96
    small_h = max(16, int(96 * height / max(width, 1)))
    if small_h > 128:
        small_h = 128
        small_w = max(16, int(128 * width / max(height, 1)))
    small = rgba.resize((small_w, small_h), Image.LANCZOS)
    pixels = small.load()
    background = _median_corner_color(pixels, small_w, small_h)
    mask: list[list[bool]] = []
    quantized_colors: set[tuple[int, int, int]] = set()
    edge_hits = 0
    comparisons = 0
    for y in range(small_h):
        row: list[bool] = []
        for x in range(small_w):
            r, g, b, a = pixels[x, y]
            active = a > 12 and (a < 245 or _color_distance((r, g, b), background) > 30.0)
            row.append(active)
            if active:
                quantized_colors.add((r // 24, g // 24, b // 24))
            if x > 0:
                pr, pg, pb, pa = pixels[x - 1, y]
                comparisons += 1
                if abs(r - pr) + abs(g - pg) + abs(b - pb) + abs(a - pa) > 42:
                    edge_hits += 1
            if y > 0:
                pr, pg, pb, pa = pixels[x, y - 1]
                comparisons += 1
                if abs(r - pr) + abs(g - pg) + abs(b - pb) + abs(a - pa) > 42:
                    edge_hits += 1
        mask.append(row)
    component_count = _estimate_component_count(mask)
    color_count = len(quantized_colors)
    edge_density = edge_hits / max(comparisons, 1) * 100.0
    content_fill = float(quality.get("content_fill_percent", 0))
    spec_objects = len(slot.get("secondary_objects") if isinstance(slot.get("secondary_objects"), list) else [])
    spec_micro = len(slot.get("micro_details") if isinstance(slot.get("micro_details"), list) else [])
    object_count_estimate = max(component_count, 1 + min(4, spec_objects // 2))
    detail_score = min(
        100.0,
        content_fill * 0.30
        + min(color_count, 24) * 1.25
        + min(edge_density, 28.0) * 1.15
        + min(component_count, 8) * 4.0
        + min(spec_objects + spec_micro, 8) * 2.5,
    )
    target = float(slot.get("detail_score_target") or (45 if _simple_allowed_slot(slot) else 65))
    object_target = int(slot.get("object_count_target") or (1 if _simple_allowed_slot(slot) else 3))
    simple_icon_risk = False
    issue_tags: list[str] = []
    if not _simple_allowed_slot(slot):
        if detail_score < target:
            simple_icon_risk = True
            issue_tags.append("too_simple")
        if object_count_estimate < object_target:
            simple_icon_risk = True
            issue_tags.append("generic_icon")
        if content_fill >= 85 and color_count <= 4 and edge_density < 3:
            simple_icon_risk = True
            issue_tags.append("single_object_on_blank_background")
    if not str(slot.get("reference_crop_path", "")).strip():
        issue_tags.append("reference_crop_ignored")
    if not str(slot.get("reference_style_profile_path", "")).strip():
        issue_tags.append("style_drift")
    return {
        "detail_score": round(detail_score, 2),
        "detail_score_target": target,
        "object_count_estimate": object_count_estimate,
        "object_count_target": object_target,
        "simple_icon_risk": simple_icon_risk,
        "reference_crop_match": "planned_reference_crop_grounded" if str(slot.get("reference_crop_path", "")).strip() else "missing_reference_crop",
        "style_match": "planned_reference_style_grounded" if str(slot.get("reference_style_profile_path", "")).strip() else "missing_reference_style",
        "color_bin_count": color_count,
        "edge_density_percent": round(edge_density, 2),
        "component_count_estimate": component_count,
        "complexity_kind": slot.get("complexity_kind") or "pipeline_module",
        "required_visual_complexity": slot.get("required_visual_complexity") or "dense",
        "complexity_issue_tags": sorted(set(issue_tags)),
    }


def _select_candidate(candidate_reports: list[dict]) -> dict:
    passing = [item for item in candidate_reports if not item.get("issue_tags")]
    pool = passing or candidate_reports
    return max(pool, key=lambda item: item["selection_score"])


def _make_contact_sheet(asset_paths: Iterable[Path], output_path: Path, title: str = "selected assets") -> None:
    paths = list(asset_paths)
    thumbs = []
    cell_w, cell_h = 260, 228
    for path in paths:
        img = Image.open(path).convert("RGB")
        img.thumbnail((224, 162), Image.LANCZOS)
        cell = Image.new("RGB", (cell_w, cell_h), "white")
        draw = ImageDraw.Draw(cell)
        cell.paste(img, ((cell_w - img.width) // 2, 14))
        draw.text((10, 184), path.stem[:34], fill=(20, 20, 20))
        thumbs.append(cell)
    cols = 5
    rows = max(1, (len(thumbs) + cols - 1) // cols)
    header_h = 34
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h + header_h), (245, 247, 248))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), title, fill=(20, 20, 20))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * cell_w, header_h + (index // cols) * cell_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _generate_one_candidate(slot: dict, style: dict, path: Path, asset_mode: str, candidate_index: int, prompt: str, retries: int = 2) -> str:
    support_color = ""
    if isinstance(slot.get("reference_dominant_colors"), list) and slot.get("reference_dominant_colors"):
        support_color = str(slot["reference_dominant_colors"][0])
    elif isinstance(style.get("reference_palette"), list) and style.get("reference_palette"):
        support_color = str(style["reference_palette"][0])
    if asset_mode == "placeholder":
        _draw_placeholder(slot, path, style, candidate_index=candidate_index)
        _enforce_target_canvas_ratio(path, slot["target_canvas_ratio"])
        _fit_subject_to_canvas(path, min_fill=float(slot.get("min_content_fill_percent", 85)), max_margin=float(slot.get("max_empty_margin_percent", 10)), support_color=support_color)
        return "explicit_placeholder_candidate"
    if asset_mode == "gemini":
        ok = _call_gemini(prompt, slot["target_canvas_ratio"], path, retries=retries)
        if not ok:
            raise RuntimeError(f"Gemini returned no image for slot {slot['id']} candidate {candidate_index}")
        _enforce_target_canvas_ratio(path, slot["target_canvas_ratio"])
        _fit_subject_to_canvas(path, min_fill=float(slot.get("min_content_fill_percent", 85)), max_margin=float(slot.get("max_empty_margin_percent", 10)), support_color=support_color)
        return "gemini_candidate_generation"
    if asset_mode == "image2":
        ok = _call_image2(prompt, slot["target_canvas_ratio"], path, retries=retries)
        if not ok:
            raise RuntimeError(f"image2 returned no image for slot {slot['id']} candidate {candidate_index}")
        _enforce_target_canvas_ratio(path, slot["target_canvas_ratio"])
        _fit_subject_to_canvas(path, min_fill=float(slot.get("min_content_fill_percent", 85)), max_margin=float(slot.get("max_empty_margin_percent", 10)), support_color=support_color)
        return f"image2_candidate_generation:{_image2_model_name()}"
    raise ValueError(f"Unsupported asset_mode: {asset_mode}")


def _generation_failure_report(slot: dict, candidate_index: int, path: Path, exc: Exception) -> dict:
    return {
        "candidate_index": candidate_index,
        "path": str(path),
        "source": "generation_failed",
        "width": 0,
        "height": 0,
        "content_bbox_px": [0, 0, 0, 0],
        "content_fill_percent": 0.0,
        "min_content_fill_percent": slot["min_content_fill_percent"],
        "empty_margin_percent": 100.0,
        "max_empty_margin_percent": slot["max_empty_margin_percent"],
        "ratio_mismatch_percent": 100.0,
        "edge_cutoff_status": "unknown_generation_failed",
        "ratio_status": "unknown_generation_failed",
        "issue_tags": ["generation_failed"],
        "selection_score": -9999.0,
        "detail_score": 0.0,
        "detail_score_target": float(slot.get("detail_score_target") or (45 if _simple_allowed_slot(slot) else 65)),
        "object_count_estimate": 0,
        "object_count_target": int(slot.get("object_count_target") or (1 if _simple_allowed_slot(slot) else 3)),
        "simple_icon_risk": True,
        "reference_crop_match": "unknown_generation_failed",
        "style_match": "unknown_generation_failed",
        "complexity_issue_tags": ["generation_failed"],
        "action": "candidate_rejected",
        "error": str(exc),
    }


def _generate_and_score_candidate(task: dict) -> dict:
    slot = task["slot"]
    candidate_path = task["path"]
    try:
        source = _generate_one_candidate(
            slot,
            task["style"],
            candidate_path,
            task["asset_mode"],
            task["candidate_index"],
            task["prompt"],
            retries=task["asset_retries"],
        )
        quality = _estimate_quality(candidate_path, slot, task["candidate_index"], source)
        complexity = _estimate_complexity(candidate_path, slot, quality)
        issue_tags = sorted(set(list(quality.get("issue_tags", [])) + list(complexity.get("complexity_issue_tags", []))))
        quality.update(complexity)
        quality["issue_tags"] = issue_tags
        complexity_penalty = 0.0
        if complexity.get("simple_icon_risk"):
            complexity_penalty += 35.0
        complexity_penalty += max(0.0, float(complexity.get("detail_score_target", 0)) - float(complexity.get("detail_score", 0))) * 0.75
        quality["selection_score"] = round(float(quality.get("selection_score", 0)) + float(complexity.get("detail_score", 0)) * 0.35 - complexity_penalty, 2)
        quality["action"] = "ok_no_crop" if not issue_tags else "candidate_rejected"
        return quality
    except Exception as exc:
        return _generation_failure_report(slot, task["candidate_index"], candidate_path, exc)


def generate_assets(
    program: dict,
    style: dict,
    out_dir: str | Path,
    asset_mode: str = "gemini",
    candidates_per_slot: int = 3,
    asset_workers: int = 1,
    asset_retries: int = 2,
) -> dict:
    out = Path(out_dir)
    assets_dir = ensure_dir(out / "assets")
    candidates_root = ensure_dir(out / "asset_candidates")
    candidates_per_slot = max(1, min(5, int(candidates_per_slot)))
    asset_workers = max(1, min(12, int(asset_workers)))
    asset_retries = max(0, min(5, int(asset_retries)))

    prompt_lines = [
        "# Summary",
        "Slot-level image prompts generated after paper brief, reference slot analysis, style sheet, layout_plan.json, figure_program.json, and slot_prompt_plan.json.",
        "Each prompt inherits the model-planned image_prompt_core for its slot before adding canvas, fill, text-control, and no-crop constraints.",
        f"Each slot generates {candidates_per_slot} candidate image block(s) with up to {asset_workers} worker(s); the selected asset is copied into `assets/` without semantic cropping.",
        "",
    ]
    report_items = []
    complexity_items = []
    selected_paths = []
    all_candidate_paths = []
    tasks = []
    ordered_slot_candidates: dict[str, list[dict]] = {}

    for slot in program["slots"]:
        slot_candidate_dir = ensure_dir(candidates_root / slot["id"])
        ordered_slot_candidates[slot["id"]] = []
        prompt_lines.append(f"## {slot['id']}")
        prompt_lines.append(f"Paper concept: {slot['paper_concept']}")
        prompt_lines.append(f"Prompt plan id: {slot.get('prompt_plan_id', 'missing')}")
        prompt_lines.append(f"Visual spec id: {slot.get('visual_spec_id', 'missing')}")
        prompt_lines.append(f"Complexity kind: {slot.get('complexity_kind', 'pipeline_module')}")
        prompt_lines.append(f"Image prompt core: {slot.get('image_prompt_core', '')}")
        prompt_lines.append("")

        for candidate_index in range(1, candidates_per_slot + 1):
            prompt = build_slot_prompt(slot, style, candidate_index=candidate_index)
            candidate_path = slot_candidate_dir / f"candidate_{candidate_index:02d}.png"
            prompt_lines.extend([f"### Candidate {candidate_index}", prompt, ""])
            task = {
                "slot": slot,
                "style": style,
                "path": candidate_path,
                "asset_mode": asset_mode,
                "candidate_index": candidate_index,
                "prompt": prompt,
                "asset_retries": asset_retries,
            }
            tasks.append(task)
            ordered_slot_candidates[slot["id"]].append(task)

    reports_by_key: dict[tuple[str, int], dict] = {}
    if asset_workers == 1 or len(tasks) <= 1:
        for task in tasks:
            report = _generate_and_score_candidate(task)
            reports_by_key[(task["slot"]["id"], task["candidate_index"])] = report
    else:
        with ThreadPoolExecutor(max_workers=asset_workers) as executor:
            futures = {executor.submit(_generate_and_score_candidate, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                reports_by_key[(task["slot"]["id"], task["candidate_index"])] = future.result()

    for slot in program["slots"]:
        candidate_reports = [
            reports_by_key[(slot["id"], candidate_index)]
            for candidate_index in range(1, candidates_per_slot + 1)
        ]
        successful_reports = [item for item in candidate_reports if Path(item.get("path", "")).exists() and "generation_failed" not in item.get("issue_tags", [])]
        all_candidate_paths.extend(Path(item["path"]) for item in successful_reports)
        if not successful_reports:
            errors = "; ".join(item.get("error", "unknown generation failure") for item in candidate_reports)
            raise RuntimeError(f"All candidate generations failed for slot {slot['id']}: {errors}")
        selected = _select_candidate(candidate_reports)
        selected_path = Path(selected["path"])
        final_asset_path = assets_dir / f"{slot['asset_id']}.png"
        shutil.copyfile(selected_path, final_asset_path)
        selected_paths.append(final_asset_path)

        selected_action = "ok_no_crop" if not selected.get("issue_tags") else "selected_best_but_needs_regeneration"
        selected_reason = (
            "Selected because it had the best combined fill, margin, ratio, and visual-complexity score."
            if not selected.get("issue_tags")
            else "Selected as the least-bad candidate but validation should fail until regenerated."
        )
        report_items.append({
            "asset_id": slot["asset_id"],
            "slot_id": slot["id"],
            "path": str(final_asset_path),
            "selected_candidate_index": selected["candidate_index"],
            "selected_candidate_path": selected["path"],
            "source": selected["source"],
            "content_fill_percent": selected["content_fill_percent"],
            "min_content_fill_percent": slot["min_content_fill_percent"],
            "empty_margin_percent": selected["empty_margin_percent"],
            "max_empty_margin_percent": slot["max_empty_margin_percent"],
            "ratio_mismatch_percent": selected["ratio_mismatch_percent"],
            "edge_cutoff_status": selected["edge_cutoff_status"],
            "ratio_status": selected["ratio_status"],
            "issue_tags": selected.get("issue_tags", []),
            "action": selected_action,
            "detail_score": selected.get("detail_score"),
            "detail_score_target": selected.get("detail_score_target"),
            "object_count_estimate": selected.get("object_count_estimate"),
            "object_count_target": selected.get("object_count_target"),
            "simple_icon_risk": selected.get("simple_icon_risk"),
            "reference_crop_match": selected.get("reference_crop_match"),
            "style_match": selected.get("style_match"),
            "complexity_issue_tags": selected.get("complexity_issue_tags", []),
            "selected_reason": selected_reason,
            "notes": "Selected from candidates; no semantic crop used; inserted into PPT with contain-fit.",
            "rejected_candidates": [item for item in candidate_reports if item["candidate_index"] != selected["candidate_index"]],
        })
        complexity_items.append({
            "asset_id": slot["asset_id"],
            "slot_id": slot["id"],
            "selected_candidate_index": selected["candidate_index"],
            "selected_candidate_path": selected["path"],
            "complexity_kind": selected.get("complexity_kind") or slot.get("complexity_kind"),
            "required_visual_complexity": selected.get("required_visual_complexity") or slot.get("required_visual_complexity"),
            "detail_score": selected.get("detail_score"),
            "detail_score_target": selected.get("detail_score_target"),
            "object_count_estimate": selected.get("object_count_estimate"),
            "object_count_target": selected.get("object_count_target"),
            "simple_icon_risk": selected.get("simple_icon_risk"),
            "reference_crop_match": selected.get("reference_crop_match"),
            "style_match": selected.get("style_match"),
            "complexity_issue_tags": selected.get("complexity_issue_tags", []),
            "selected_reason": selected_reason,
            "candidate_complexity": [
                {
                    "candidate_index": item.get("candidate_index"),
                    "path": item.get("path"),
                    "detail_score": item.get("detail_score"),
                    "object_count_estimate": item.get("object_count_estimate"),
                    "simple_icon_risk": item.get("simple_icon_risk"),
                    "reference_crop_match": item.get("reference_crop_match"),
                    "style_match": item.get("style_match"),
                    "complexity_issue_tags": item.get("complexity_issue_tags", []),
                    "selection_score": item.get("selection_score"),
                }
                for item in candidate_reports
            ],
        })

    write_text(out / "prompts.md", "\n".join(prompt_lines))
    report = {
        "summary": "Asset quality report for multi-candidate slot-level generated blocks.",
        "candidate_policy": {
            "candidates_per_slot": candidates_per_slot,
            "selection": "prefer passing candidates; otherwise choose highest fill/margin/ratio score and fail validation if below thresholds",
            "no_crop": True,
        },
        "assets": report_items,
    }
    write_json(out / "asset_quality_report.json", report)
    complexity_report = {
        "summary": "Asset complexity report for selected slot-level generated blocks.",
        "policy": "Reject normal non-legend assets that look like sparse generic icons, ignore the local crop, or lack layered visual detail.",
        "assets": complexity_items,
    }
    write_json(out / "asset_complexity_report.json", complexity_report)
    _make_contact_sheet(selected_paths, out / "asset_contact_sheet.png", title="selected slot assets")
    _make_contact_sheet(all_candidate_paths, out / "asset_candidate_contact_sheet.png", title="all generated candidates")
    return report
