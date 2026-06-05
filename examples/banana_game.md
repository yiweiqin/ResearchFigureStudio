# Summary

This example runs the BananaGame paper through ResearchFigureStudio using the current engineering pipeline. Use the placeholder command first to validate structure, then run a small real image job before spending API budget on a full 36-slot multi-candidate run.

## Inputs

- Paper: `C:\Users\zhang\Downloads\BananaGame_EMNLP26_YichiChuyu (1).pdf`
- Reference image: `D:\LiveFigure\output\test_run_banana_architecture\00_reference_gemini.png`

If the reference path is unavailable, provide a new user reference image. The workflow should not generate its own full reference image unless explicitly requested.

## Offline Validation Run

```powershell
$out='D:\ResearchFigureStudio\output\banana_full_pipeline_placeholder_36'
if (Test-Path $out) { Remove-Item -LiteralPath $out -Recurse -Force }
rfs make-framework --paper 'C:\Users\zhang\Downloads\BananaGame_EMNLP26_YichiChuyu (1).pdf' --reference 'D:\LiveFigure\output\test_run_banana_architecture\00_reference_gemini.png' --out $out --asset-mode placeholder --locator-mode heuristic --prompt-plan-mode heuristic --slot-count 36 --candidates-per-slot 3 --asset-review-mode heuristic --critic-mode heuristic --json
rfs validate --out $out --json
```

## Small Real Image Run

```powershell
$out='D:\ResearchFigureStudio\output\banana_real_small_25x1'
rfs make-framework --paper 'C:\Users\zhang\Downloads\BananaGame_EMNLP26_YichiChuyu (1).pdf' --reference 'D:\LiveFigure\output\test_run_banana_architecture\00_reference_gemini.png' --out $out --asset-mode gemini --asset-workers 3 --asset-retries 2 --locator-mode vlm --prompt-plan-mode vlm --prompt-plan-workers 4 --slot-count 25 --candidates-per-slot 1 --asset-review-mode heuristic --critic-mode heuristic --json
```

## Full Quality Run

```powershell
$out='D:\ResearchFigureStudio\output\banana_real_36x3_vlm'
rfs make-framework --paper 'C:\Users\zhang\Downloads\BananaGame_EMNLP26_YichiChuyu (1).pdf' --reference 'D:\LiveFigure\output\test_run_banana_architecture\00_reference_gemini.png' --out $out --asset-mode gemini --asset-workers 4 --asset-retries 2 --locator-mode vlm --prompt-plan-mode vlm --prompt-plan-workers 4 --slot-count 36 --candidates-per-slot 3 --asset-review-mode vlm --critic-mode vlm --critic-iterations 1 --json
```

## Expected Outputs

- `editable_composition.pptx`
- `layout_plan.json`
- `figure_program.json`
- `assets/*.png`
- `asset_candidates/*/candidate_*.png`
- `asset_contact_sheet.png`
- `asset_candidate_contact_sheet.png`
- `asset_quality_report.json`
- `asset_visual_review.json`
- `visual_critic_iter_0.json`
- `critic_report.md`
