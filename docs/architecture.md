# Summary

ResearchFigureStudio is organized as a small deterministic pipeline, not a patched copy of LiveFigure. The only borrowed idea is reference-image-based positioning: a VLM can look at the reference image and return normalized coordinates in `layout_plan.json`.

## Architecture

```text
Input Loader
  -> Paper Analyzer
  -> Reference Analyzer
  -> Stylist
  -> Layout Locator
  -> Figure Program Builder
  -> Prompt Planner
  -> Asset Generator
  -> Asset Reviewer
  -> PPT Compiler
  -> Exporter
  -> Visual Critic
  -> Validator
```

## Modules

- `rfs/input_archive.py`: copies paper and reference into `out/inputs/` and writes `input_manifest.json`.
- `rfs/input_loader.py`: extracts text from source documents.
- `rfs/paper_analyzer.py`: creates paper-grounded figure brief.
- `rfs/reference_analyzer.py`: creates 25-50 slot inventory from the reference image geometry and paper figure goal.
- `rfs/stylist.py`: writes the style sheet before image prompting.
- `rfs/layout_locator.py`: creates `layout_plan.json`; heuristic mode is local, VLM mode returns JSON coordinates only.
- `rfs/program_builder.py`: creates `figure_program.json`, the single source for PPT compilation.
- `rfs/prompt_planner.py`: creates `reference_slot_prompt_brief.json` and `slot_prompt_plan.json`; default VLM mode inspects the full reference image plus local slot crops and writes `image_prompt_core` for each slot. Per-slot calls can run in parallel via `--prompt-plan-workers`.
- `rfs/asset_generator.py`: generates 1-5 candidates per slot, selects the best block, and writes contact sheets and QA metrics.
- `rfs/asset_reviewer.py`: performs heuristic or VLM visual review of selected assets.
- `rfs/ppt_compiler.py`: renders editable PPTX from `figure_program.json` with contain-fit images and editable labels/arrows/groups.
- `rfs/exporter.py`: exports PDF/PNG where local tooling supports it.
- `rfs/visual_critic.py`: compares reference and final render; VLM mode can propose JSON coordinate corrections.
- `rfs/validator.py`: blocks delivery when required artifacts or hard constraints are missing.

## Non-Goals

- Do not import LiveFigure as a dependency.
- Do not let a VLM write arbitrary PowerPoint code.
- Do not generate a single full architecture image and crop it into pieces.
- Do not make SVG the main editing source.
- Do not bake critical scientific text, formulas, arrows, or labels into image blocks.

## Data Contracts

- `slot_inventory.json`: paper concept plus candidate slot metadata.
- `layout_plan.json`: normalized positions, panels, arrows, and z order.
- `figure_program.json`: final composition program consumed by the PPT compiler.
- `reference_slot_prompt_brief.json`: per-slot paper concept, local reference role, geometry, and function briefing sent before prompt planning.
- `slot_prompt_plan.json`: VLM-generated per-slot prompt plan, including `image_prompt_core`, `must_show`, and `avoid_showing`.
- `asset_quality_report.json`: fill/margin/ratio/cutoff/candidate-selection metrics.
- `asset_visual_review.json`: semantic and visual review of selected image blocks.
- `visual_critic_iter_*.json`: reference alignment and optional coordinate correction proposals.
