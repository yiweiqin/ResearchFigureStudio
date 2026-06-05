# Summary

The workflow is designed to keep scientific content, layout, image generation, and PPT editability separated. This prevents the project from becoming a fragile script pile where coordinates, prompts, and rendered assets are mixed together.

## Full Workflow

1. Archive the paper and reference image into the output directory.
2. Extract the paper brief: title, method story, named modules, variables, and figure goal.
3. Analyze the reference image and create 25-50 slot targets.
4. Create the style sheet before any image prompt is written.
5. Create `layout_plan.json`; use VLM only for normalized coordinate estimation when enabled.
6. Create `figure_program.json`; this is the only layout source for the PPT compiler.
7. Write `reference_slot_prompt_brief.json`; it records what each local reference slot does and what paper concept it carries.
8. Write `slot_prompt_plan.json`; default `--prompt-plan-mode vlm` calls the model for each slot and produces `image_prompt_core`. Use `--prompt-plan-workers` to run these per-slot VLM calls in parallel.
9. Generate multiple image candidates per slot from the model-planned prompt core.
10. Select assets by fill, margin, ratio, and cutoff metrics; never use semantic cropping.
11. Review selected assets with heuristic or VLM review.
12. Compile `editable_composition.pptx` deterministically from the figure program.
13. Export PDF/PNG for review where possible.
14. Run visual critic against the reference image and rendered output.
15. Write alignment review and critic report.
16. Run `rfs validate` before delivery.

## Recommended Development Runs

Offline engineering check:

```powershell
rfs make-framework --paper "C:\path\paper.pdf" --reference "C:\path\reference.png" --out D:\ResearchFigureStudio\output\offline_check --asset-mode placeholder --locator-mode heuristic --prompt-plan-mode heuristic --slot-count 36 --candidates-per-slot 3 --asset-review-mode heuristic --critic-mode heuristic --json
rfs validate --out D:\ResearchFigureStudio\output\offline_check --json
```

Small real image check:

```powershell
rfs make-framework --paper "C:\path\paper.pdf" --reference "C:\path\reference.png" --out D:\ResearchFigureStudio\output\real_small --asset-mode gemini --asset-workers 3 --asset-retries 2 --locator-mode vlm --prompt-plan-mode vlm --prompt-plan-workers 4 --slot-count 25 --candidates-per-slot 1 --asset-review-mode heuristic --critic-mode heuristic --json
```

Full quality run:

```powershell
rfs make-framework --paper "C:\path\paper.pdf" --reference "C:\path\reference.png" --out D:\ResearchFigureStudio\output\full_quality --asset-mode gemini --asset-workers 4 --asset-retries 2 --locator-mode vlm --prompt-plan-mode vlm --prompt-plan-workers 4 --slot-count 36 --candidates-per-slot 3 --asset-review-mode vlm --critic-mode vlm --critic-iterations 1 --json
```

## Parallel Asset Generation

- `--prompt-plan-workers` controls concurrent VLM calls for per-slot prompt planning. Use 4 by default; raise carefully if Yunwu rate limits allow it.
- `--asset-workers` controls concurrent candidate image requests. Use 3-4 for the first Yunwu/Gemini run.
- `--asset-retries` controls retries per candidate. Retry handles transient 429, 5xx, and timeout failures.
- Candidate failures are recorded as rejected candidates. A slot only blocks the run when all of its candidates fail.
- The pipeline does not silently switch to placeholder mode when Gemini fails.

## Failure Policy

Validation should fail if any of these occur:

- fewer than 25 selected slot assets
- missing PPTX main editable source
- missing `layout_plan.json`, `figure_program.json`, `reference_slot_prompt_brief.json`, or `slot_prompt_plan.json`
- missing asset review or visual critic output
- single full diagram image used as the final figure
- vector-only or SVG-only fallback for image-rich requests
- semantic cropping, cover-crop, or crop-to-ratio
- asset fill below 80% or empty margin above 12%
- critical labels or formulas baked into generated images
