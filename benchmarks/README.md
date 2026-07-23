# ResearchFigureStudio Benchmarks

ResearchFigureStudio uses two independent product benchmark suites plus a generated PDF extraction stress suite, so failures can be attributed to paper parsing, reference-image generation, or editable reconstruction.

## Suites

### `paper-to-image`

Measures scientific faithfulness, terminology, relation correctness, information coverage and density, clarity, aesthetics, reference compliance, hallucinations, and stability across repeated generations.

Scientific errors are hard failures and cannot be offset by aesthetics.

### `image-to-ppt`

Measures rendered visual fidelity, object and relation reconstruction, text alignment, editable PowerPoint structure, anti-cheating rules, visual blockers, and eventually edit-mutation behavior.

A full-slide copy of the reference image is a hard failure even if pixel similarity is perfect.

### Generated PDF extraction stress suite

`benchmark pdf-suite` creates deterministic native two-column, unnumbered-bold-section, rotated-page, and mixed native/scanned PDFs at runtime. It validates section boundaries, cross-column reading order, displayed coordinates, caption recovery, local OCR scheduling, English OCR spacing recovery, and elapsed time. `--ocr-engine auto` adds a real installed-OCR probe after the deterministic adapter-backed tier.

## Commands

```powershell
rfs benchmark list --root benchmarks --json
rfs benchmark validate --case benchmarks/paper-to-image/cases/001_linear_pipeline --json
rfs benchmark fetch --case benchmarks/paper-to-image/cases/101_vit_linear --json
rfs benchmark fast --case benchmarks/paper-to-image/cases/101_vit_linear --out output/benchmarks/vit_fast --planner-mode heuristic --json
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/fast_suite --planner-mode heuristic --json
rfs benchmark pdf-suite --out output/benchmarks/pdf_extraction --ocr-engine auto --json
rfs benchmark run --case benchmarks/paper-to-image/cases/001_linear_pipeline --out output/benchmarks/p2i_001 --json
rfs benchmark score --case benchmarks/image-to-ppt/cases/001_three_stage_layout --run output/rebuild_case --json
```

## Case policy

Each case contains `case.json` plus suite-specific human-authored ground truth. Synthetic cases may be committed. Real papers and figures should only be committed when redistribution is permitted; otherwise use local paths or a private benchmark data repository.

Generated runs and reports belong under `output/benchmarks/` and are not source fixtures.

Real-paper cases commit `source.json` and human-authored Ground Truth, while `benchmark fetch` downloads the PDF into an ignored local `inputs/` directory. This keeps the public repository reproducible without redistributing publisher files.

The committed unseen-generalization set spans vision, multimodal learning, and NLP: ViT, Mask R-CNN, Self-Refine, ImageBind, SAM, DETR, CLIP, NeRF, Transformer, BERT, and retrieval-augmented generation. The NLP cases specifically exercise short overview captions, method-text recovery, embedding summation, pre-training/fine-tuning separation, and retrieval-conditioned generation. Local image-only scan regressions remain under ignored `tmp/pdfs/` and `output/pdf/`; do not commit publisher PDFs or generated OCR artifacts.

`benchmark fast-suite` writes `fast_suite_report.json` with per-case results and aggregate entity/relation recall, forbidden content, cache hit rates, provider success/retry counts, failure categories, and stage timings.

## Evaluation tiers

- Offline contract tier: placeholder assets, deterministic validation, CI-safe.
- Fast planning tier: entity recall, relation recall, forbidden content, evidence grounding, deadline, and cache behavior without image generation.
- Production quality tier: real VLM/image models, frozen judge, repeated seeds, and human calibration.
- Human audit tier: blinded pairwise ratings for aesthetics, clarity, and information density.
