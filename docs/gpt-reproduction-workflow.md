# GPT Reproduction Workflow For ResearchFigureStudio

This document is written for another GPT/Codex-style agent that needs to reproduce, inspect, or continue the current ResearchFigureStudio workflow without reading the full project conversation.

## Mission

ResearchFigureStudio is a PPTX-first research-figure reconstruction system. The current reference-only workflow takes one figure image and rebuilds it as an editable PowerPoint composition:

- editable PPT text boxes from OCR
- editable panels/cards/connectors/arrows
- slot-level raster assets for complex icons or illustrations
- no full-reference-image background in the final PPT
- JSON contracts and overlays for inspection and manual correction

The main user-facing command is:

```powershell
rfs rebuild-editable --reference input.png --out output\demo --asset-mode api --export-preview
```

For higher-quality reference-only reproduction, use the scripted professional workflow. It asks the VLM to generate a controlled Figure DSL that mimics the best one-off rebuild scripts, then compiles that DSL safely:

```powershell
rfs rebuild-editable-pro --reference input.png --out output\demo_pro --asset-mode api --asset-policy smart-api --repair-rounds 2 --export-preview
```

The evaluation command is:

```powershell
rfs rebuild-editable-eval --reference input.png --out output\eval --asset-mode crop --export-preview
```

## Repository Context

Important modules:

```text
rfs/editable_rebuild.py          Main reference-only rebuild pipeline.
rfs/layout_planner.py            Panel/card/slot layout detection and overlay.
rfs/control_localizer.py         Arrow/control detection, VLM binding, overlay.
rfs/layout_semantic_planner.py   Slot semantic planning from OCR/layout/control context.
rfs/rebuild_vlm_adapters.py      Real VLM adapters for layout/control/semantic stages.
rfs/vlm_client.py                Shared OpenAI-compatible VLM JSON client.
rfs/rebuild_vlm_validation.py    VLM output validation report.
rfs/rebuild_eval.py              Heuristic vs hybrid VLM evaluator.
rfs/professional_rebuild.py      Scripted professional DSL rebuild pipeline.
rfs/professional_dsl.py          Controlled DSL schema and validation.
rfs/ppt_compiler.py              PPTX compiler from figure_program.json.
rfs/text_layer.py                OCR/fallback editable text layer.
rfs/cli.py                       CLI entrypoints.
```

Existing one-off scripts in `scripts/` are historical examples. Do not treat them as the product entrypoint unless the user explicitly asks for that specific old reproduction.

## Environment Setup

Install locally:

```powershell
cd <path-to-ResearchFigureStudio>
python -m pip install --upgrade pip
python -m pip install -e .
```

Optional OCR:

```powershell
python -m pip install -e ".[ocr]"
```

Check environment:

```powershell
rfs doctor --json
```

VLM planning uses an OpenAI-compatible chat-completions endpoint:

```powershell
$env:API_BASE='https://your-openai-compatible-provider/v1'
$env:API_KEY='<your key>'
$env:MODEL_VLM='your-vision-language-model'
$env:RFS_REBUILD_LAYOUT_MODEL=$env:MODEL_VLM
$env:RFS_REBUILD_CONTROL_MODEL=$env:MODEL_VLM
$env:RFS_REBUILD_SEMANTIC_MODEL=$env:MODEL_VLM
$env:RFS_PROFESSIONAL_REBUILD_MODEL=$env:MODEL_VLM
```

Slot-level image generation uses the Gemini-style image endpoint:

```powershell
$env:GEMINI_API_KEY=$env:API_KEY
$env:GEMINI_GEN_IMG_URL='https://your-provider/v1beta/models/your-image-model:generateContent'
```

Never write API keys into source files, docs, fixtures, or committed outputs.

## Recommended GPT Execution Flow

### 1. Start With A Cost-Safe Evaluation

Use crop/placeholder assets first only as an engineering check. The evaluator may use crop for cost-safe structure comparison; production/pro runs should use `smart-api` so crop is not inserted as a final PPT asset:

```powershell
rfs rebuild-editable-eval `
  --reference "C:\path\figure.png" `
  --out "output\eval_case" `
  --asset-mode crop `
  --text-mode ocr `
  --export-preview
```

Inspect:

```text
output/eval_case/rebuild_vlm_eval_summary.json
output/eval_case/case_heuristic/reference_geometry_overlay.png
output/eval_case/case_heuristic/reference_controls_overlay.png
output/eval_case/case_vlm/reference_geometry_overlay.png
output/eval_case/case_vlm/reference_controls_overlay.png
output/eval_case/case_vlm/rebuild_vlm_validation_report.json
output/eval_case/case_vlm/editable_composition.pptx
```

Decision rule:

- If `case_vlm` has better panel/slot/arrow overlays than `case_heuristic`, continue to a full rebuild.
- If VLM output is worse or invalid, inspect `rebuild_vlm_validation_report.json` and improve prompts/schema before spending image-generation credits.

### 2. Run The Full Rebuild

Use this only after the crop evaluation looks acceptable:

```powershell
rfs rebuild-editable `
  --reference "C:\path\figure.png" `
  --out "output\editable_rebuild" `
  --asset-mode api `
  --asset-policy smart-api `
  --layout-mode hybrid `
  --control-mode hybrid `
  --text-mode ocr `
  --export-preview
```

Expected outputs:

```text
input_manifest.json
reference_geometry.json
reference_geometry_overlay.png
reference_text_geometry.json
reference_controls.json
reference_controls_overlay.png
slot_inventory.json
slot_semantic_report.json
asset_generation_specs.json
asset_generation_report.json
asset_economy_report.json
asset_ratio_fit_report.json
figure_program.json
composition_quality_report.json
rebuild_vlm_validation_report.json
editable_composition.pptx
rebuild_preview.png or preview_export_error.txt
```

### 3. Manual JSON Correction Loop

If overlays are close but not good enough, edit JSON contracts directly:

```text
reference_geometry.json    panel/card/slot bboxes and ids
reference_controls.json    arrow source/target/path/style
slot_inventory.json        slot semantic fields if needed
```

Then recompile without analysis or asset regeneration:

```powershell
rfs rebuild-editable `
  --reference "C:\path\figure.png" `
  --out "output\editable_rebuild" `
  --compile-only `
  --export-preview
```

If geometry/control is good but assets need rerun:

```powershell
rfs rebuild-editable `
  --reference "C:\path\figure.png" `
  --out "output\editable_rebuild" `
  --skip-analysis `
  --asset-mode api `
  --regenerate-slots slot_a,slot_b
```

Use `accepted_assets.json` to lock assets the user has approved:

```json
{
  "slot_a": {"accepted": true},
  "slot_b": {"accepted": true}
}
```

## Quality Gates

A result is acceptable only if:

- `editable_composition.pptx` exists and opens.
- The final PPT does not use the full reference image as a slide background.
- Main text is editable PPT text, not baked into the full figure.
- Panels, connectors, arrows, and labels are editable PPT objects.
- Complex visuals are slot-level assets under `assets/`.
- `rebuild_vlm_validation_report.json` has `status: pass` or only explainable warnings.
- `asset_generation_report.json` records API request counts and fallbacks.
- `asset_decision_report.json`, `text_asset_filter_report.json`, and `api_asset_plan.json` explain which slots are API-generated, reused, or rejected as text.
- `reference_geometry_overlay.png` and `reference_controls_overlay.png` visually match the reference closely enough for the current stage.

For `rfs rebuild-editable-pro`, additionally check:

- `professional_rebuild_script.dsl.json` exists and uses only controlled DSL objects.
- `professional_rebuild_validation.json` has `status: pass`.
- `professional_rebuild_notes.md` records whether VLM planning or fallback was used.
- `professional_gap_report.json` shows whether pro output improved over baseline and, when configured, approaches a specialized benchmark output.
- Use `--compile-only` after manual DSL edits to avoid extra VLM/image API calls.
- Use `--repair-mode vlm` only when preview export exists and constrained DSL patching is acceptable; otherwise keep the default `--repair-mode report`.

Important report checks:

```text
rebuild_vlm_validation_report.json
  layout.vlm_status
  control.vlm_status
  semantic.semantic_vlm_status
  layout.invalid_bbox_ids
  control.invalid_arrow_ids
  semantic.invalid_asset_type_ids

asset_generation_report.json
  api_requests_attempted
  fallback_used
  foreground_bbox_fill_percent
  selected_reason

composition_quality_report.json
  rebuild_editable_summary.contains_full_reference_image
  rebuild_editable_summary.text_shape_count
  rebuild_editable_summary.connector_count
```

## Cost-Safe Modes

Use these modes deliberately:

```powershell
# No API, engineering smoke test.
rfs rebuild-editable --reference input.png --out output\placeholder --asset-mode placeholder --layout-mode heuristic --control-mode heuristic

# VLM structure test without image generation cost.
rfs rebuild-editable --reference input.png --out output\crop --asset-mode crop --asset-policy smart-api --layout-mode hybrid --control-mode hybrid

# Full quality run.
rfs rebuild-editable --reference input.png --out output\api --asset-mode api --asset-policy smart-api --layout-mode hybrid --control-mode hybrid
```

Default economy behavior:

- Existing passing assets are reused.
- Accepted assets are locked by `accepted_assets.json`.
- Only failed or explicitly requested slots are regenerated.
- `--strict-asset-regeneration --asset-retries N` is opt-in and more expensive.

## Common Failure Modes

### VLM unavailable

Symptoms:

```text
vlm_status: unavailable_fallback_to_heuristic
```

Action:

- Check `API_BASE`, `API_KEY` or `GEMINI_API_KEY`, and `MODEL_VLM`.
- Run `rfs doctor --json`.
- If still blocked, use `--layout-mode heuristic --control-mode heuristic`.

### VLM returns bad JSON

Symptoms:

```text
vlm_status: fallback
warnings include JSON parsing or validation errors
```

Action:

- Inspect the corresponding report.
- Tighten the prompt in `rfs/rebuild_vlm_adapters.py`.
- Add or update tests before changing production behavior.

### Arrows are misplaced

Action:

- First inspect `reference_controls_overlay.png`.
- If VLM source/target is wrong, edit `reference_controls.json`.
- Prefer fixing `path_percent` over relying on automatic connector routing.
- Recompile with `--compile-only`.

### Text looks wrong

Action:

- Inspect `reference_text_geometry.json` and `text_program.json`.
- Confirm OCR is available or use `python -m pip install -e ".[ocr]"`.
- Adjust bbox/font fields in JSON, then recompile.

### Asset content is too small

Action:

- Inspect `asset_generation_specs.json` for `generation_aspect_ratio`, `main_subject_fill_target`, and `prompt_subject`.
- Regenerate only failed slots with `--regenerate-slots`.
- Do not use reference crops as final PPT assets in smart-api/pro runs. Crops are context for API generation only.

## Test Commands

Run before claiming implementation is stable:

```powershell
python -m py_compile rfs\*.py
python -m unittest discover -s tests -p "test*.py"
```

Current expected baseline after the VLM eval implementation:

```text
40 tests OK
```

If tests write temporary previews or outputs, confirm they do not modify tracked source files unintentionally.

## How To Continue Development

When another GPT/Agent continues this project:

1. Read this file and `docs/rebuild-editable.md`.
2. Run `git status --short` and do not delete user-created untracked scripts.
3. Run a crop-mode eval before any expensive API generation.
4. Prefer adding validation/reporting before changing generation behavior.
5. Keep `rfs make-framework` compatible; reference-only work should stay under `rfs rebuild-editable`.
6. Use `apply_patch` for source edits and keep changes scoped.

The most useful next improvements are:

- stronger JSON schema validation for VLM outputs
- better curved/dashed arrow detection
- asset-level VLM review before regeneration
- a small benchmark set with expected overlay/object counts
- a visual UI for editing bbox and arrow paths instead of hand-editing JSON
