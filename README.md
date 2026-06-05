# ResearchFigureStudio

## Summary

ResearchFigureStudio is a PPTX-first research figure generation pipeline for paper-grounded, reference-guided scientific framework figures. It turns a paper plus a user-provided visual reference image into an editable PowerPoint composition assembled from many slot-level image assets, not one flattened full-diagram bitmap.

The current workflow is optimized for AI/ML/NLP system figures:

- paper-grounded concept extraction
- reference-primary geometry, style, color, and flow alignment
- 25-50 non-arrow image slots
- `slot_visual_spec.json` for dense mini-scene/image-block planning
- multi-candidate image generation through placeholder, Gemini, or Yunwu image2-compatible APIs
- deterministic PPTX composition with editable labels, panels, arrows, connectors, and formulas
- strict validation for no single full diagram, no semantic crop, no vector-only fallback, low blank space, and non-trivial image-block complexity

This repository does not include API keys, papers, reference images, generated outputs, or local run artifacts.

## Installation

```powershell
git clone https://github.com/yiweiqin/ResearchFigureStudio.git
cd ResearchFigureStudio
python -m pip install --upgrade pip
python -m pip install -e .
rfs doctor --json
```

Windows with PowerPoint installed gives the best PPTX/PDF/PNG export path. The Python package itself can still generate and validate most intermediate artifacts without external image APIs when using `--asset-mode placeholder`.

## Offline Smoke Test

Use placeholder assets to validate the local pipeline without calling any API:

```powershell
rfs make-framework `
  --paper "C:\path\paper.pdf" `
  --reference "C:\path\reference.png" `
  --out "output\demo_placeholder" `
  --slot-count 25 `
  --slot-source reference-primary `
  --complexity-profile reference-dense `
  --candidates-per-slot 2 `
  --locator-mode heuristic `
  --prompt-plan-mode heuristic `
  --asset-mode placeholder `
  --asset-workers 4 `
  --asset-review-mode heuristic `
  --critic-mode heuristic `
  --json

rfs validate --out "output\demo_placeholder" --json
```

`output/` is intentionally ignored by Git.

## Real VLM + Image Generation

Set API credentials only through environment variables. Do not write keys into source files.

```powershell
$env:API_BASE='https://yunwu.ai/v1'
$env:API_KEY='<your key>'
$env:GEMINI_API_KEY=$env:API_KEY
$env:GEMINI_GEN_IMG_URL='https://yunwu.ai/v1beta/models/gemini-2.5-flash-image:generateContent'
$env:MODEL_VLM='gemini-3-pro-preview-thinking'
$env:RFS_PROMPT_PLANNER_MODEL=$env:MODEL_VLM
$env:RFS_IMAGE_MODEL='image-2'
```

Recommended real run:

```powershell
rfs make-framework `
  --paper "C:\path\paper.pdf" `
  --reference "C:\path\reference.png" `
  --out "output\paper_reference_image2" `
  --slot-count 40 `
  --slot-source reference-primary `
  --complexity-profile reference-dense `
  --candidates-per-slot 4 `
  --locator-mode vlm `
  --prompt-plan-mode vlm `
  --prompt-plan-workers 8 `
  --asset-mode image2 `
  --asset-workers 6 `
  --asset-retries 3 `
  --asset-review-mode heuristic `
  --critic-mode heuristic `
  --json
```

Use lower worker counts if your API provider rate-limits requests.

## Workflow

```text
input archive -> paper brief -> reference_geometry.json/reference_controls.json ->
reference_style_profile.json/style_sheet.md -> layout_plan.json -> figure_program.json ->
slot_visual_spec.json -> reference_slot_prompt_brief.json -> slot_prompt_plan.json ->
multi-candidate slot assets -> asset_quality_report.json -> asset_complexity_report.json ->
asset_visual_review.json/contact sheets -> editable_composition.pptx -> PDF/PNG export ->
visual_critic_iter_0.json -> critic_report.md -> validation
```

Key rules:

- The reference image is the source of truth for layout, local visual object choice, color, visual rhythm, and arrow logic when `--slot-source reference-primary` is used.
- The paper provides scientific terminology and concept mapping; it should not override the reference image into a generic template.
- Arrows, connector lines, dashed loops, panel frames, labels, formulas, and critical text are PPT editable objects, not image assets.
- Normal non-legend slots should be dense mini scientific scenes/cards with layered objects and micro-details, not simple centered icons.
- Generated images are inserted with no semantic cropping.

## Output Contract

A valid image-rich framework run should include:

- `input_manifest.json`
- `paper_brief.md` / `paper_brief.json`
- `reference_geometry.json`
- `reference_controls.json`
- `reference_style_profile.json`
- `style_sheet.md`
- `layout_plan.json`
- `figure_program.json`
- `slot_visual_spec.json`
- `reference_slot_prompt_brief.json`
- `slot_prompt_plan.json`
- `prompts.md`
- `reference_slot_crops/<slot_id>.png`
- `assets/*.png` with at least 25 selected non-arrow image assets
- `asset_candidates/*/candidate_*.png`
- `asset_quality_report.json`
- `asset_complexity_report.json`
- `asset_visual_review.json`
- `asset_contact_sheet.png`
- `asset_candidate_contact_sheet.png`
- `editable_composition.pptx`
- `review.pdf` and `final_600dpi.png` when local export is available
- `visual_critic_iter_0.json`
- `alignment_review.md`
- `critic_report.md`

Run validation:

```powershell
rfs validate --out "output\paper_reference_image2" --json
python codex-skills\research-figure-making\scripts\validate_framework_outputs.py "output\paper_reference_image2"
```

## Codex Skill

This repository includes the Codex skill under:

```text
codex-skills/research-figure-making
```

To install it locally into Codex:

```powershell
$dst = Join-Path $env:USERPROFILE ".codex\skills\research-figure-making"
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
Copy-Item -Recurse "codex-skills\research-figure-making" $dst
```

The skill documents the full research-figure workflow and includes the standalone framework-output validator.

## Development

```powershell
python -m compileall -q rfs
python -m unittest discover -s tests -q
python -m py_compile codex-skills\research-figure-making\scripts\validate_framework_outputs.py
```

## Repository Hygiene

Do not commit:

- `output/`
- papers, manuscripts, private datasets, or user reference images
- generated PPTX/PDF/PNG/JPG/SVG assets
- `.env` files or API keys
- cache folders such as `__pycache__/` or `*.egg-info/`

## License

MIT License. See [LICENSE](LICENSE).
