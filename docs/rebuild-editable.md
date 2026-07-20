# Image-to-Editable-PPT Rebuild

`rfs rebuild-editable` is the reference-only workflow for turning one figure image into an editable PowerPoint-first rebuild. `rfs rebuild-editable-pro` is the higher-quality scripted workflow: it asks a VLM to produce a controlled Figure DSL that mimics the repository's best one-off rebuild scripts, then interprets that DSL through the same safe compiler.

The v1 goal is reproducibility and inspectability: panels, text, connectors, and simple structure are PPT objects; complex visual blocks are slot-level raster assets. The command does not place the full reference image as the final slide background.

## Quick Start

```powershell
rfs rebuild-editable --reference input.png --out output\demo --asset-mode api --economy-mode
```

Offline engineering run:

```powershell
rfs rebuild-editable --reference input.png --out output\demo_placeholder --asset-mode placeholder --export-preview
```

Only rerun selected assets:

```powershell
rfs rebuild-editable --reference input.png --out output\demo --regenerate-slots slot_03,slot_07
```

High-cost strict regeneration:

```powershell
rfs rebuild-editable --reference input.png --out output\demo --asset-mode api --strict-asset-regeneration --asset-retries 5
```

Professional scripted rebuild:

```powershell
rfs rebuild-editable-pro --reference input.png --out output\demo_pro --asset-mode api --asset-policy smart-api --repair-rounds 2 --export-preview
```

Compare against a known high-quality specialized rebuild:

```powershell
rfs rebuild-editable-pro --reference input.png --out output\demo_pro --asset-mode crop --asset-policy smart-api --benchmark-out output\autofigure_architecture_ai_rebuild
```

Offline professional smoke test:

```powershell
rfs rebuild-editable-pro --reference input.png --out output\demo_pro_placeholder --asset-mode placeholder --text-mode off
```

## Main Options

```text
--reference              Input reference image.
--out                    Output directory.
--asset-mode             api | crop | placeholder. Default: api.
--asset-policy           legacy | smart-api. Default: smart-api. Use legacy only for old crop-fallback behavior.
--asset-workers          Parallel asset workers. Default: 4.
--asset-retries          Retries used by strict regeneration. Default: 1.
--economy-mode           Reuse accepted/passing assets. Enabled by default.
--no-economy-mode        Disable economy reuse decisions.
--regenerate-slots       Comma-separated slot ids to rerun.
--text-mode              ocr | manual | off. Default: ocr.
--layout-mode            heuristic | vlm | hybrid. Default: hybrid.
--ocr-engine             paddle | easyocr | off. Default: paddle.
--ocr-lang               en | ch | en_ch. Default: en_ch.
--control-mode           heuristic | vlm | hybrid | manual. Default: hybrid.
--skip-analysis          Reuse existing JSON contracts in --out.
--compile-only           Recompile PPTX from existing JSON contracts and assets.
--export-preview         Export rebuild_preview.png when PowerPoint is available.
```

Professional-only options:

```text
rebuild-editable-pro     Use the controlled professional Figure DSL workflow.
--repair-rounds          Preview repair reports to write/run. Default: 2.
--repair-mode            report | vlm. Default: report. vlm applies controlled DSL patches.
--benchmark-out          Optional specialized output directory for professional_gap_report.json.
--compile-only           Recompile from professional_rebuild_script.dsl.json without VLM planning or asset API calls.
```

`smart-api` disables final reference-crop assets. Local crops are still saved and passed as API reference context, but final PPT assets are API-generated, reused from another generated slot, or skipped when the region is primarily editable text. If `--asset-mode crop --asset-policy smart-api` is used for a low-cost dry run, the final visual asset is a placeholder and the report records `crop_disabled_by_smart_api_policy_placeholder`.

## API Environment

`--asset-mode api` uses the same image-generation route as the specialized rebuild scripts:

```text
GEMINI_API_KEY or API_KEY
GEMINI_GEN_IMG_URL
```

Hybrid VLM layout/control/semantic planning uses an OpenAI-compatible chat completions endpoint:

```text
API_BASE
API_KEY or GEMINI_API_KEY
MODEL_VLM
RFS_REBUILD_LAYOUT_MODEL    optional
RFS_REBUILD_CONTROL_MODEL   optional
RFS_REBUILD_SEMANTIC_MODEL  optional
RFS_PROFESSIONAL_REBUILD_MODEL optional, used by rebuild-editable-pro
```

PowerShell example:

```powershell
$env:API_BASE='https://your-openai-compatible-provider/v1'
$env:API_KEY='<your key>'
$env:MODEL_VLM='your-vision-language-model'
$env:RFS_REBUILD_LAYOUT_MODEL=$env:MODEL_VLM
$env:RFS_REBUILD_CONTROL_MODEL=$env:MODEL_VLM
$env:RFS_REBUILD_SEMANTIC_MODEL=$env:MODEL_VLM
$env:RFS_PROFESSIONAL_REBUILD_MODEL=$env:MODEL_VLM
$env:GEMINI_API_KEY=$env:API_KEY
$env:GEMINI_GEN_IMG_URL='https://your-provider/v1beta/models/your-image-model:generateContent'
```

With `--asset-policy legacy`, if the API call fails for a slot, v1 falls back to the reference crop for that slot and records the failure in `asset_generation_report.json`. With `--asset-policy smart-api`, crop fallback is disabled; API failure falls back to a placeholder and records `api_failed_placeholder_fallback`.

## Output Files

The workflow writes these files:

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
asset_decision_report.json
text_asset_filter_report.json
api_asset_plan.json
figure_program.json
composition_quality_report.json
rebuild_vlm_validation_report.json
editable_composition.pptx
rebuild_preview.png or preview_export_error.txt
```

`rebuild-editable-pro` additionally writes:

```text
professional_rebuild_plan.json
professional_rebuild_script.dsl.json
professional_rebuild_validation.json
professional_rebuild_notes.md
professional_gap_report.json
professional_repair_round_N.json
```

`figure_program.json` is the PPT compiler source of truth. `reference_text_geometry.json` stores OCR or fallback text geometry. `reference_controls.json` stores editable connector candidates. `slot_inventory.json` stores non-text visual asset slots.

## Analysis And Manual Correction

`--layout-mode hybrid` uses local CV candidates first and can accept a VLM layout planner when one is wired in. Without a VLM adapter, it falls back to heuristic layout and records that status in `reference_geometry.json`.

`--control-mode hybrid` uses CV line detection plus fallback sequence connectors and can accept a VLM/control planner for source-target binding. Detected connector paths are written as `path_percent`, and the PPT compiler uses those points directly.

Review overlays:

```text
reference_geometry_overlay.png
reference_controls_overlay.png
```

After manually editing JSON contracts, recompile without rerunning analysis or image generation:

```powershell
rfs rebuild-editable --reference input.png --out output\demo --compile-only
```

For the professional workflow, edit `professional_rebuild_script.dsl.json` and recompile without rerunning VLM planning or image-generation API calls:

```powershell
rfs rebuild-editable-pro --reference input.png --out output\demo_pro --compile-only --export-preview
```

`--repair-mode vlm` is intentionally constrained. It may only patch DSL fields such as `bbox_percent`, `font_size_pt`, `path_percent`, `stroke_color`, `stroke_width_pt`, `prompt_subject`, `background_color_hex`, `generation_aspect_ratio`, and `content_fill_target`. It cannot add arbitrary objects or execute generated Python.

`professional_gap_report.json` compares baseline counts, professional DSL counts, and optional benchmark counts. Use it to see whether the pro workflow is moving toward the best specialized scripts in text count, connector count, panel/card structure, and slot coverage.

To keep existing analysis contracts but rerun OCR, asset specs, and placeholder/API asset handling:

```powershell
rfs rebuild-editable --reference input.png --out output\demo --skip-analysis --asset-mode placeholder
```

## VLM Evaluation

Use the paired evaluator before spending image-generation credits. It runs one
heuristic case and one hybrid VLM case, both using `--asset-mode crop` by
default:

```powershell
rfs rebuild-editable-eval --reference input.png --out output\eval --asset-mode crop --export-preview
```

The evaluator writes:

```text
rebuild_vlm_eval_summary.json
case_heuristic/
case_vlm/
```

Compare the two cases using:

```text
reference_geometry_overlay.png
reference_controls_overlay.png
rebuild_vlm_validation_report.json
rebuild_preview.png
editable_composition.pptx
```

Only run a full `--asset-mode api` rebuild after the VLM case clearly improves
layout, control binding, and slot semantics.

## Cost Control

Economy mode is on by default:

- Existing assets are reused when they pass type-aware fill thresholds.
- Assets listed as accepted in `accepted_assets.json` are locked and reused.
- Each failed slot generates one candidate by default.
- `--regenerate-slots` reruns only named slots.
- `--strict-asset-regeneration --asset-retries N` opts into higher-cost retries.

Accepted assets file example:

```json
{
  "slot_03": {"accepted": true},
  "slot_07": {"accepted": true}
}
```

Type-aware fill thresholds:

```text
character:      80%-95%
document_stack: 75%-95%
chart_card:     75%-95%
tool_icon:      80%-95%
inspection:     70%-95%
tool_combo:     70%-95%
device:         70%-95%
screenshot_card:75%-95%
legend_marker:  80%-95%
thin_tool:      50%-95%
```

## Current Limits

This is a reusable baseline, not a pixel-perfect designer replacement. Hybrid mode is designed to accept stronger VLM layout/control planners, but it still falls back safely when they are unavailable. Complex layouts, curved arrows, and panel semantics may still need manual JSON correction. OCR is optional and falls back safely when local OCR is unavailable.
