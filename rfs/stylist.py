from __future__ import annotations

from pathlib import Path
from .utils import write_json, write_text


def build_style_sheet(paper_brief: dict, inventory: dict, out_dir: str | Path) -> dict:
    reference_palette = [str(item) for item in inventory.get("reference_palette", []) if str(item).strip()]
    if len(reference_palette) < 4:
        base = reference_palette[0] if reference_palette else "#8A8F96"
        reference_palette = reference_palette + [base] * (4 - len(reference_palette))
    panel_styles = inventory.get("panel_styles", {}) if isinstance(inventory.get("panel_styles"), dict) else {}
    color_tokens = inventory.get("color_tokens", []) if isinstance(inventory.get("color_tokens"), list) else []
    reference_style_profile = {
        "summary": "Machine-readable reference style profile extracted before prompt planning and PPT composition.",
        "style_summary": "Reference-first polished scientific illustration; preserve the user-provided reference figure's layout, color rhythm, icon/card treatment, and connector language.",
        "illustration_style": "match the reference crop style for each slot: academic flat / soft 2.5D illustration, compact dense icons, rounded scientific cards when present",
        "line_weight": "inherit reference line weights; use clean medium outlines for icons and thinner editable PPT connectors",
        "shadow_style": "inherit shallow reference shadows only where visible; avoid neon glow or generic poster lighting",
        "corner_radius": "derive from reference panels/cards; use rounded rectangles only where the reference uses them",
        "background_texture": "slot backgrounds should follow local crops; no extra white tile or blank presentation mat",
        "icon_detail_level": "high detail for small scientific icons; concrete object silhouette first, decorative marks second",
        "visual_density": "dense but readable; content fills 90-97% and empty margin stays below 10%",
        "text_policy": "critical labels, formulas, arrows, metrics, and panel IDs are editable PPT objects; generated images may contain only tiny decorative non-critical marks",
        "reference_priority": "reference_image_primary; paper_terms_only_for_scientific_mapping",
        "color_tokens": color_tokens,
        "panel_styles": panel_styles,
        "palette": reference_palette[:12],
    }
    write_json(Path(out_dir) / "reference_style_profile.json", reference_style_profile)
    style = {
        "summary": "Unified visual style sheet generated before slot image prompts.",
        "palette": reference_palette[:8],
        "reference_palette": reference_palette[:12],
        "reference_style_profile_path": "reference_style_profile.json",
        "reference_style_profile": reference_style_profile,
        "color_tokens": color_tokens,
        "panel_styles": panel_styles,
        "line_weight_pt": 1.6,
        "arrow_weight_pt": 2.0,
        "shadow": "soft but shallow; no poster-like glow",
        "viewpoint": "mechanism-first scientific illustration; use flat, 2.5D, or cutaway views only when they clarify the slot mechanism",
        "icon_complexity": "medium-high for meso cards; micro icons must still show paper-specific structure, not generic line icons",
        "background": "white slide background; PPT containers inherit reference panel colors; slot images are inserted frameless without extra white tiles",
        "content_fill_target": "90-97% useful visual content",
        "margin_policy": "every edge empty margin must stay below 10%; safe area prevents cutoff but does not create large blank borders",
        "background_fill_strategy": "supporting texture/card surfaces extend near edges",
        "icon_scale_rule": "single-object icons fill most of the slot without clipped edges",
        "card_density_rule": "cards should maximize useful visual density and avoid sparse white boxes, but repeated generic UI panels are forbidden",
        "style_diversity_rule": "panel and slot colors come from the reference image tokens; do not collapse the figure into one blue-green palette",
        "font_layer_rules": "critical labels, formulas, arrows, panel ids, and variables are editable PPT text, never trusted from image generation",
        "image2_text_policy": "allow very small decorative non-critical UI marks only; no key scientific terms, formulas, fake axes, or metrics",
        "slot_frame_policy": "frameless_slot",
        "picture_fill_policy": "direct_full_slot_contain_no_tile",
    }
    lines = [
        "# Summary",
        style["summary"],
        "",
        "## Visual Direction",
        f"- Reference palette: {', '.join(style['reference_palette'])}",
        f"- Reference style profile: {style['reference_style_profile_path']}",
        f"- Color token count: {len(color_tokens)}",
        f"- Viewpoint: {style['viewpoint']}",
        f"- Icon complexity: {style['icon_complexity']}",
        f"- Background: {style['background']}",
        f"- Style diversity: {style['style_diversity_rule']}",
        f"- Slot frame policy: {style['slot_frame_policy']}",
        f"- Picture fill policy: {style['picture_fill_policy']}",
        "",
        "## Fill And Margin Rules",
        f"- Content fill target: {style['content_fill_target']}",
        f"- Margin policy: {style['margin_policy']}",
        f"- Background fill: {style['background_fill_strategy']}",
        f"- Icon scale: {style['icon_scale_rule']}",
        f"- Card density: {style['card_density_rule']}",
        "",
        "## PPT Text Layer Rules",
        f"- {style['font_layer_rules']}",
        f"- Image text policy: {style['image2_text_policy']}",
    ]
    write_text(Path(out_dir) / "style_sheet.md", "\n".join(lines) + "\n")
    return style
