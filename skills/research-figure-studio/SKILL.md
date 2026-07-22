---
name: research-figure-studio
description: Create paper-grounded, editable PowerPoint scientific framework figures from papers and optional visual references. Use for paper-to-PPT figures, editable architecture diagrams, method overviews, system pipelines, or image-to-editable-PPT reconstruction.
---

# Research Figure Studio

## Summary

Create scientifically faithful figures whose labels, entities, and relations come from the paper, while generated images or user references provide layout and visual style. The deliverable is an editable PPTX, not a flattened diagram image.

## Preferred route

Use the installed `rfs` command from any working directory. Do not assume a repository location or embed machine-specific paths.

For a complete paper-to-editable workflow:

```powershell
rfs paper-to-editable --paper <paper> --out <output_dir> --positive-reference <optional_reference> --json
```

For image-only reconstruction:

```powershell
rfs rebuild-editable --reference <image> --out <output_dir> --asset-policy smart-api --json
```

Use `--image-asset-mode placeholder --rebuild-asset-mode placeholder --allow-engineering-preview` only for explicit offline engineering validation. Never present that result as production-approved.

For paper understanding or prompt-only work, start with:

```powershell
rfs doctor --json
rfs inspect-pdf --paper <paper.pdf> --out <inspection_dir> --json
rfs fast-framework-prompt --paper <paper.pdf> --out <fast_result> --deadline 180 --json
```

`inspect-pdf` and the fast path share a global document cache. For scanned PDFs, `auto` prefers RapidOCR when installed. Do not enable automatic EasyOCR model downloads implicitly; use `RFS_OCR_ALLOW_DOWNLOAD=1` only when the user explicitly wants the one-time download.

## Required semantic policy

- Read and structure the paper before generating the visual reference.
- Treat `paper_review.json` and `figure_specification.json` as scientific ground truth.
- Treat the generated/reference image as layout and style evidence only.
- Keep exact paper labels, relations, formulas, numbers, and citations out of raster assets whenever possible.
- Bind paper entities and relations into editable PPT text and connector objects through `paper_semantic_contract.json` and `semantic_binding_report.json`.
- Never reconstruct scientific truth by OCR alone when paper contracts are available.
- Never promote a failed candidate or engineering preview to production output automatically.

## Workflow

1. Archive the paper and references.
2. Build the evidence map and structured paper review.
3. Validate evidence grounding, including relations whose endpoints may be inputs, outputs, concepts, research objects, modules, or innovations.
4. Plan the figure and generate candidate reference images.
5. Stop if no production candidate passes all gates.
6. Analyze the selected image globally before local extraction.
7. Rebuild panels, cards, assets, editable labels, and editable connectors.
8. Apply the paper semantic contract so exact labels and scientific relations override image/OCR guesses.
9. Generate deterministic visual QA and a fallback preview.
10. Validate the PPTX and report warnings or blockers.

## References

Read only what the task needs:

- Paper analysis: `references/paper_to_figure.md`
- Framework figures: `references/visual_framework_figures.md`
- User-provided image alignment: `references/reference_image_alignment.md`
- Structured figure program: `references/figure_program.md`
- Image block prompting: `references/image_block_prompting.md`
- Critic and delivery gates: `references/critic_stage.md` and `references/journal_quality_checklist.md`
- Data plots: `references/data_figures.md`

## Delivery checklist

The normal paper-to-editable output should contain:

- `paper_to_image/paper_review.json`
- `paper_to_image/figure_specification.json`
- `paper_to_image/planning_validation_report.json`
- `editable/paper_semantic_contract.json`
- `editable/semantic_binding_report.json`
- `editable/figure_program.json`
- `editable/text_program.json`
- `editable/rebuild_visual_quality_report.json`
- `editable/editable_composition.pptx`
- `editable/rebuild_preview.png` when preview export is requested

If production gates fail, return the engineering artifacts and the blocker; do not claim that the figure is ready for paper submission.

## Benchmark commands

Use the two independent suites to locate failures before changing the workflow:

```powershell
rfs benchmark list --root benchmarks --json
rfs benchmark fetch --case <case_dir> --json
rfs benchmark fast --case <case_dir> --out <run_dir> --deadline 180 --json
rfs benchmark fast-suite --root benchmarks --out <suite_dir> --planner-mode heuristic --json
rfs benchmark run --case <case_dir> --out <run_dir> --json
rfs benchmark score --case <case_dir> --run <run_dir> --json
```

`paper-to-image` scientific and terminology errors are hard failures. `image-to-ppt` must reject full-slide reference images even when raster similarity is high.

For prompt-only work, inspect `extraction_report.json`, `contract_completion_report.json`, and `planning_validation_report.json` in that order. Treat `engineering_only: true` as non-production even when deterministic topology coverage is high. Use `fast-suite` after parser or contract changes and reject regressions in forbidden content, evidence grounding, provider reliability, or stage timings.
