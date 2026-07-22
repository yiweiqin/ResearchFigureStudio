# ResearchFigureStudio Benchmarks

ResearchFigureStudio uses two independent benchmark suites so failures can be attributed to either reference-image generation or editable reconstruction.

## Suites

### `paper-to-image`

Measures scientific faithfulness, terminology, relation correctness, information coverage and density, clarity, aesthetics, reference compliance, hallucinations, and stability across repeated generations.

Scientific errors are hard failures and cannot be offset by aesthetics.

### `image-to-ppt`

Measures rendered visual fidelity, object and relation reconstruction, text alignment, editable PowerPoint structure, anti-cheating rules, visual blockers, and eventually edit-mutation behavior.

A full-slide copy of the reference image is a hard failure even if pixel similarity is perfect.

## Commands

```powershell
rfs benchmark list --root benchmarks --json
rfs benchmark validate --case benchmarks/paper-to-image/cases/001_linear_pipeline --json
rfs benchmark fetch --case benchmarks/paper-to-image/cases/101_vit_linear --json
rfs benchmark fast --case benchmarks/paper-to-image/cases/101_vit_linear --out output/benchmarks/vit_fast --planner-mode heuristic --json
rfs benchmark run --case benchmarks/paper-to-image/cases/001_linear_pipeline --out output/benchmarks/p2i_001 --json
rfs benchmark score --case benchmarks/image-to-ppt/cases/001_three_stage_layout --run output/rebuild_case --json
```

## Case policy

Each case contains `case.json` plus suite-specific human-authored ground truth. Synthetic cases may be committed. Real papers and figures should only be committed when redistribution is permitted; otherwise use local paths or a private benchmark data repository.

Generated runs and reports belong under `output/benchmarks/` and are not source fixtures.

Real-paper cases commit `source.json` and human-authored Ground Truth, while `benchmark fetch` downloads the PDF into an ignored local `inputs/` directory. This keeps the public repository reproducible without redistributing publisher files.

## Evaluation tiers

- Offline contract tier: placeholder assets, deterministic validation, CI-safe.
- Fast planning tier: entity recall, relation recall, forbidden content, evidence grounding, deadline, and cache behavior without image generation.
- Production quality tier: real VLM/image models, frozen judge, repeated seeds, and human calibration.
- Human audit tier: blinded pairwise ratings for aesthetics, clarity, and information density.
