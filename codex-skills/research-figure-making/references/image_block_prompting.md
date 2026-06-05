# Image Block Prompting

Use this reference when generating image2 visual blocks for framework figures.
The goal is to create many slot-sized blocks that fit the reference image layout
by matching each slot's canvas ratio before generation. Do not rely on
post-generation cropping to force a block into a slot.

## Summary

Generate full-frame, visually dense slot assets. The subject should normally fill
90%-97% of the canvas, with 85% as the minimum passing fill. Safe area prevents
cut-off content; it is not permission to leave large blank margins.

## Prompt Inputs

Each prompt must be based on a slot inventory entry:

- paper concept
- target canvas ratio
- exact target canvas ratio
- precise `center_percent`, `width_percent`, `height_percent`,
  `aspect_ratio_decimal`, `aspect_ratio_w_h`, and `target_pixels_exact` from
  `reference_geometry.json`
- `target_pixels` equal to `target_pixels_exact`, plus `generation_min_pixels`
  for the minimum generation resolution safeguard
- target slot size or pixel box
- local reference crop path, usually `reference_slot_crops/<slot_id>.png`
- local color token IDs and `reference_style_profile.json`
- parent macro panel
- visual density
- fit policy
- text policy
- reference style notes

Each prompt must also read:

- the matching `figure_program.json` slot entry, including `slot_id`,
  `parent_panel`, `bbox_percent`, `safe_area_percent`, `fit_policy`, and
  `asset_id`
- the matching `reference_slot_prompt_brief.json` entry, which records what this
  reference slot does and what paper concept it carries
- the matching `slot_visual_spec.json` entry, which records
  `reference_crop_objects`, `foreground_subject`, `secondary_objects`,
  `micro_details`, `background_fill_elements`,
  `scientific_mechanism_detail`, `required_visual_complexity`, and
  `forbidden_simplification`
- the matching `slot_prompt_plan.json` entry, which must provide VLM-planned
  `slot_function`, `reference_slot_role`, `reference_shape_language`,
  `reference_local_style`, `reference_prompt_hint`, `visual_metaphor`,
  `must_show`, `avoid_showing`, and `image_prompt_core`
- the local reference crop used by the prompt planner; final image2 text prompts
  must explicitly say the slot was planned from this crop and should recreate
  the local reference object's shape, density, and color before minor paper
  adaptation
- the matching `layout_plan.json` slot entry when present, because this is the
  reference-guided positioning source
- `reference_style_profile.json` and `style_sheet` fields for palette, color
  token IDs, line style, viewpoint, icon complexity, background, visual density,
  and image2 text policy
- the slot fill fields: `target_content_fill_percent`,
  `min_content_fill_percent`, `max_empty_margin_percent`, `composition_type`,
  and `blank_space_policy`

Do not write prompts for broad macro panels when the figure needs editable
detail. Generate meso cards and micro icons instead.

## Style And Program Inheritance

Before writing prompts, confirm that `style_sheet.md` or `style_sheet.json`,
`layout_plan.json`, `figure_program.json`, `reference_slot_prompt_brief.json`,
and `slot_prompt_plan.json` already exist. The prompt must not invent a new
style, new slot placement, or generic visual metaphor. It should translate the
VLM-planned `image_prompt_core` plus existing slot and style constraints into
image2/Gemini instructions.

Default prompt planning should use the API/VLM route, not heuristic prompt
planning. Heuristic prompt planning is only for offline engineering validation
or when the user explicitly requests a no-API run. For normal 25-50 slot
figures, run per-slot prompt planning with parallel VLM workers when the API
rate limit allows it. This is independent from image-generation parallelism:
`prompt-plan-workers` speeds up `slot_prompt_plan.json`, while `asset-workers`
speeds up Gemini/Yunwu image asset generation.

The VLM planner must first describe what is actually visible in the local
reference crop before adapting the slot to the paper concept. For non-legend
slots, the final prompt must request a dense mini scientific scene/card with
2-5 layered objects, edge-to-edge supporting detail, and no standalone
pictogram. Legend/badge slots may be simpler, but still need a full-frame
composition with minimal blank canvas.

Prompt records in `prompts.md` should include:

- `prompt_id`
- `slot_id`
- `asset_id`
- source `paper_concept`
- copied `target_canvas_ratio`
- copied `center_percent`
- copied `width_percent`
- copied `height_percent`
- copied `aspect_ratio_decimal`
- copied `aspect_ratio_w_h`
- copied `target_pixels`
- copied `target_pixels_exact`
- copied `generation_min_pixels`
- copied `fit_policy`
- copied `text_policy`
- copied `target_content_fill_percent`
- copied `min_content_fill_percent`
- copied `max_empty_margin_percent`
- copied `composition_type`
- copied style sheet name or hash
- copied `reference_crop_path`
- copied `reference_style_profile_path`
- copied `local_color_token_ids`
- copied `visual_spec_id`
- copied `complexity_kind`
- copied `foreground_subject`
- copied `secondary_objects`
- copied `micro_details`
- copied `background_fill_elements`
- copied `scientific_mechanism_detail`
- copied `required_visual_complexity`
- copied `forbidden_simplification`
- copied `prompt_plan_id`
- copied `slot_function`
- copied `image_prompt_core`
- the final image2 prompt

## Blank Space Policy

Use these defaults unless the paper or reference layout requires otherwise:

- target useful content fill: 90%-97%
- minimum useful content fill: 85%
- maximum pure empty margin on any side: 10%
- subject scale: large, complete, and close to full-frame
- supporting details: extend near the canvas edge when they do not change
  scientific meaning

Safe area means the main subject, card edge, icon edge, character, chart, or
scientific cue is not cut off. It does not mean the prompt should request a
large white border. If the subject is complete but tiny, regenerate with a
stronger full-frame prompt rather than padding or cropping.

## Required Prompt Clauses

Every image2 prompt for a slot should include:

```text
Use reference_style_profile.json and local color token ids [ids].
This prompt was planned from local reference crop [reference_crop_path]; recreate
that crop's object, composition, shape, density, and color rhythm first.
Canvas aspect ratio must be exactly [precise decimal ratio from reference_geometry.json].
Use the exact slot center [center_percent], width [width_percent], and height
[height_percent] from the reference image.
Compose the full subject inside this ratio.
Use a full-frame composition with a large subject.
The useful visual content should fill 90-97% of the canvas, minimum 85%.
Every edge empty margin must stay below 10%.
Keep the key subject inside the inner safe area so it is not cut off, but do not
create a large blank border.
Extend non-critical background detail, card surfaces, or supporting texture close
to the canvas edges.
No cropping, no cut-off edges, no object extending outside the frame.
Minimal blank canvas, no tiny centered object.
For non-legend slots, create a dense mini scientific scene/card with 2-5 layered
objects, edge-to-edge supporting detail, and not a standalone pictogram.
Foreground subject: [foreground_subject].
Secondary objects: [secondary_objects].
Micro details: [micro_details].
Background fill elements: [background_fill_elements].
Scientific mechanism detail: [scientific_mechanism_detail].
Forbidden simplifications: [forbidden_simplification].
Match the reference figure style: [style notes].
Follow the project style sheet: [palette, line style, viewpoint, density].
Allow only very small non-critical decorative text if it naturally appears.
Do not include critical scientific labels, equations, variables, metrics,
axis values, panel numbers, or fake chart text.
```

Do not create image prompts for arrows, connector lines, dashed loops,
transition arrows, panel frames, or titles. Those belong in
`reference_controls.json` and the PPT editable layer.

Replace `[ratio or shape]` with concrete wording:

- `exact slot ratio 1.312:1.000`
- `exact tall slot ratio 0.538:1.000`
- `exact wide slot ratio 2.418:1.000`

Do not replace these with coarse presets such as `1:1`, `4:3`, `3:4`, `16:9`,
or `9:16`.

## Text Policy

Use three text policies:

- `none`: no visible text at all, best for tiny icons and symbols
- `decorative_only`: tiny, non-critical placeholder marks are acceptable
- `editable_overlay_required`: all meaningful text must be added later by the
  composition layer

Small decorative text is allowed only when it is not scientifically meaningful:
short UI-like marks, unreadable card headings, or vague placeholder strokes.
Never rely on image2 to create correct paper terminology, formulas, metric names,
numbers, citations, or arrows labels.

## Fit Policies

- `contain`: fit the whole generated block into the slot with no content loss
- `pad_to_fit`: add white or transparent padding only for ratio matching, not to
  fix an undersized subject
- `background_extend`: extend only plain background to match the slot ratio
- `regenerate_for_ratio`: regenerate when the canvas ratio or composition is
  wrong
- `preserve_outer_shape`: keep the outer card or badge shape fully visible

Never use center-crop, cover-crop, or forced crop-to-ratio as the default. A
small trim of pure background is acceptable only when it does not touch useful
content and does not change the subject.

Avoid default phrases such as `tight crop`, `generous margin`, `lots of
whitespace`, or `small centered object`. Use `complete large subject inside the
frame`, `full-frame composition`, and `90-97% useful content fill` instead.

## Negative Prompt Phrases

Avoid or explicitly negate these phrases:

- `large empty margin`
- `small isolated object on blank background`
- `floating tiny icon`
- `lots of white space`
- `tiny centered object`
- `generous blank border`
- `small object surrounded by blank canvas`
- `white presentation tile`
- `extra white mat`
- `large white card background`
- `simple centered icon`
- `single object on clean blank background`
- `standalone pictogram`

## Prompt Templates

Meso card:

```text
Create a compact scientific illustration card for [paper concept] in [parent
panel]. Show [visual metaphor] representing [paper-specific function]. Target
canvas aspect ratio: exactly [ratio]. Full-frame composition, full-bleed card
surface, large subject, minimal blank canvas, edge-to-edge supporting detail.
Useful visual content should fill 90-97% of the canvas, minimum 85%, while the
complete card remains visible and uncut. Include 2-5 layered objects, micro
details, and edge-to-edge support detail; do not make a standalone pictogram.
Keep key content inside the safe area without adding a large blank border. No
cropping, no cut-off card edges, no object extending outside the frame, no tiny
centered object. Style: polished
academic paper infographic, crisp black outlines, soft pastel colors, same
visual grammar as the reference figure. Allow only very small non-critical
decorative text. Do not include critical scientific labels, equations,
variables, metrics, panel numbers, axis values, or fake chart text.
```

Micro icon:

```text
Create a single isolated icon-like scientific visual for [paper concept].
Target canvas aspect ratio: exactly [ratio]. Full-frame icon composition with a
large subject, no tiny centered object, minimal blank canvas. Fit the entire
object inside the frame with all edges visible; useful visual content should
fill 90-97% of the canvas, minimum 85%, without being cut off. Background may be
white or removable, but avoid large unused white border. Style: crisp academic
infographic icon, soft pastel color, black outline, consistent with the
reference figure. No critical text, no equations, no numbers. Tiny decorative
marks are acceptable only if non-semantic.
```

Scene thumbnail:

```text
Create a compact scene thumbnail for [paper concept]. Target canvas aspect
ratio: exactly [ratio]. Compose the complete scene for this ratio from the
start; no post-generation cropping should be required. Full-frame composition,
large readable scene, edge-to-edge supporting detail, minimal blank canvas.
Keep all important characters, objects, and visual cues complete and uncut.
Useful visual content should fill 90-97% of the frame, minimum 85%, while
preserving the full scene. Style: cohesive with the reference figure, polished
paper illustration, readable at small size. No critical labels, no fake UI text,
no numbers.
```

## Post-Generation Checks

After generation:

- estimate the visible subject area against the image area
- write `asset_quality_report.json` with `summary` and per-asset metrics
- write `asset_complexity_report.json` with `summary`, `detail_score`,
  `object_count_estimate`, `simple_icon_risk`, `reference_crop_match`,
  `style_match`, and `selected_reason`
- if useful content occupies less than 80%, regenerate with a stronger fill
  instruction; do not enlarge by cropping
- if useful content is below the 88%-95% target but above 80%, keep only when the
  subject is complete and the critic accepts the density tradeoff
- if pure empty margin on any side exceeds 10%-12%, regenerate or redesign the
  prompt
- if aspect ratio differs from the slot target by more than 10%, regenerate or
  pad-to-fit; do not crop semantic content
- if any subject edge, card edge, character, icon, chart, or meaningful visual
  detail is cut off, regenerate
- reject blocks with wrong critical text, fake formulas, fake axes, or fake
  numeric charts
- reject normal non-legend blocks with unresolved `too_simple`, `generic_icon`,
  `reference_crop_ignored`, `single_object_on_blank_background`, or
  `style_drift`
- use contain-fit during assembly so the whole image remains visible
- create a contact sheet that shows every slot ID and block before assembly
