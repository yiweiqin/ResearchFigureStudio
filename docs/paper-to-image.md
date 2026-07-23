# Summary

`rfs paper-to-image` produces a reviewed raster scientific framework image without creating PPTX. Production mode requires successful VLM paper review, a content-free architecture blueprint, reference-conditioned Image2 edit generation, and four production quality gates.

## Three-Minute Fast Contract

```powershell
rfs fast-framework-prompt --paper paper.pdf --out output/fast --deadline 180 --json
```

The fast path stops before image generation. It uses structured block-level PDF extraction, complete overview captions, stable page/content-hash evidence IDs, a semantic-only VLM request, evidence-gated generic contract completion, and separate document/contract caches. Layout, style, prompt, and editable overlays are compiled deterministically after the semantic graph. A warm paper normally completes in well under a second. If no VLM succeeds, the command returns an engineering result with explicit uncertainties instead of claiming production readiness.

Use `rfs inspect-pdf --paper paper.pdf --out output/inspection --json` to diagnose reading order, Unicode, OCR, section coverage, captions, parser agreement, and evidence-page coverage without model calls. Rotated native-text pages are transformed into displayed-page coordinates before ordering, and body text is conservatively classified as one, two, or three columns; spanning titles and captions remain explicit ordering boundaries. OCR lines use the same detector, including a three-to-two-column fallback for first pages where centered title fragments otherwise resemble a third column. Quality gates count all Unicode letters and numbers. English, Chinese, Japanese, and Korean section aliases are recognized, Chinese `图/表` captions are indexed, and CJK cross-extractor agreement uses character bigrams so per-character spacing differences do not resemble corruption. Cross-extractor quality uses directional lexical coverage while retaining order-sensitive agreement for diagnostics, preventing multi-column order differences, equation variables, and Poppler-only hidden text from causing wasteful OCR. The quality report exposes the maximum detected column count, the number of multi-column pages, and all rotated page numbers. For image-only/scanned papers, `--ocr-engine auto` prefers RapidOCR. Up to three selected pages run concurrently, and short narrow or vertical fragments in the outer page margins are removed as likely watermarks/page furniture. OCR candidates are scheduled by semantic signals first (overview figures, Method, Abstract, Conclusion), then by document-wide coverage anchors instead of simply taking the first six pages. `RFS_OCR_WORKERS` overrides page concurrency.

If a long fully scanned paper cannot reach the 60% full-document readability gate within the deadline, the workflow may continue only when at least six high-confidence sampled pages cover both Abstract and Method. The result records `semantic_scope: sampled_pages_only`, includes an explicit uncertainty about unprocessed pages, and can never be production-ready. Missing Abstract/Method coverage or weak OCR still stops semantic planning. EasyOCR downloads are opt-in through `RFS_OCR_ALLOW_DOWNLOAD=1`; missing models fail quickly and still write a complete extraction report.

Run all or selected paper benchmarks with aggregate reliability metrics:

```powershell
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/fast-suite --planner-mode heuristic --json
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/unseen --case-id 106_detr_set_prediction --case-id 107_clip_contrastive --json
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/nlp --case-id 109_transformer_encoder_decoder --case-id 110_bert_pretrain_finetune --case-id 111_rag_retrieval_generation --planner-mode vlm --json
```

For OCR performance diagnosis, `extraction_report.json` and `benchmark pdf-suite` now record page rendering, text detection, orientation classification, text recognition, and post-processing time separately. RapidOCR defaults are deliberately conservative: detector limit `512`, recognition batch `6`, and up to three page workers. Advanced local experiments can override these without changing repository defaults:

```powershell
$env:RFS_RAPIDOCR_DET_LIMIT = "512"
$env:RFS_RAPIDOCR_BATCH = "6"
$env:RFS_OCR_WORKERS = "3"
rfs benchmark pdf-suite --out output/benchmarks/pdf_profile --ocr-engine rapidocr --json
```

Lower detector limits are not assumed to be faster. On dense two-column scans, recognition usually dominates and smaller detector settings can have unstable latency; accept a change only after text agreement, section recovery, caption recovery, confidence, and wall-clock gates all pass.

Deadline-limited or failed OCR schedules are explicitly marked with `ocr_schedule_complete=false` / `ocr_run_complete=false`. Such document models are never written to the global document cache, and scientifically partial scan results are never written to the semantic contract cache; a transient slow or failed OCR run therefore cannot poison later fast runs.

`fast_suite_report.json` records planning recall, forbidden content, document/contract cache hits, provider attempts and retries, failure categories, parser/semantic/total timings, readable-page ratio, evidence-page coverage, evidence character counts, maximum detected column count, multi-column page totals, OCR candidate/scheduled/completed totals, maximum OCR concurrency, and removed OCR margin-noise totals.
The deterministic compiler can recover relations across adjacent PDF blocks, canonicalize evidence-backed VLM aliases, repair missing relation evidence, and ground or downgrade unsupported scalar claims. It also normalizes string entities plus `source_id`/`target_id`/`relation_type` variants, resolves a missing endpoint only when the relation label exactly identifies one declared entity, grounds short uppercase acronyms through exact token matches, and removes unresolved relations into explicit uncertainties. These repairs are paper-name agnostic and are covered by the NLP suite.

When a paper exceeds the evidence character budget, the extractor reserves representative evidence from every page, then prioritizes topology-defining statements and Abstract, Conclusion, Method, Introduction, and Experiments content. This prevents long introductions or appendices from silently excluding later conclusions and framework definitions.

## Production Command

```powershell
$env:API_BASE='https://yunwu.ai/v1'
$env:API_KEY='<rotated-new-key>'
$env:RFS_IMAGE_MODEL='image-2'
$env:RFS_IMAGE_EDIT_URL='https://yunwu.ai/v1/images/edits'

rfs paper-to-image `
  --paper "C:\path\paper.pdf" `
  --out "output\paper_to_image" `
  --domain-profile auto `
  --positive-reference "C:\path\reference1.png" `
  --positive-reference "C:\path\reference2.png" `
  --template auto `
  --planner-mode vlm `
  --asset-mode image2 `
  --candidates 3 `
  --aspect-ratio auto `
  --review-mode vlm `
  --repair-rounds 1 `
  --ocr-engine auto `
  --json
```

Never reuse a key that has appeared in chat, source control, an issue, or a terminal transcript. The command records only `api_key_present`; it never records a key value.

## Paper Review Contract

`paper_review.json` uses a universal core plus a selected domain profile. Facts use stable IDs, evidence IDs, expanded page/section/quote references, confidence, importance, `required|optional|forbidden|unknown` status, and a figure role. The coverage validator rejects ungrounded required facts, invalid relation endpoints, missing profile sections, and duplicated training/inference steps in production mode.

Available profiles:

- `general`
- `ai-ml-method`
- `system-platform`
- `dataset-benchmark`
- `empirical-science`
- `survey-review`

## Template Contract

Positive references are classified as `arbor`, `linear`, `tripanel`, or `dense-multimodal`. Each becomes a content-free profile containing normalized panels, topology, connector rhythm, density, palette, and forbidden copied content. Automatic selection uses module count, loops/tree structure, multimodality, retrieval structure, and requested ratio.

The selected profile is rendered as `layout_blueprint.png`. The blueprint contains no reference text or reference-specific objects and is the only image supplied to Image2 edit for initial candidates.

When `--aspect-ratio auto` is used, the template keeps its internal normalized
geometry while the generation canvas uses the nearest native Image2 ratio
(`3:2`, `2:3`, or `1:1`). This avoids semantic cropping after generation.

## Production Gates

Every Image2 candidate must pass:

- exact-label OCR with no missing, misspelled, duplicate, or copied reference labels;
- scientific module and relation checks with no invention or reversal;
- template alignment score of at least `0.72` with no copied reference content;
- aesthetic score of at least `0.75`;
- valid image resolution and blueprint aspect ratio.

Scientific score must be at least `0.95`; OCR must be exact. If three candidates fail, the best candidate receives one localized Image2 edit repair. If the repair still fails, the command stops without writing `selected_image.png`.

## Engineering Mode

`--asset-mode placeholder --planner-mode heuristic --review-mode heuristic` validates contracts without API cost. It writes `engineering_preview.png`, never `selected_image.png`, and is not production eligible.
