# Summary

`rfs paper-to-image` produces a reviewed raster scientific framework image without creating PPTX. Production mode requires successful VLM paper review, a content-free architecture blueprint, reference-conditioned Image2 edit generation, and four production quality gates.

## Three-Minute Fast Contract

```powershell
rfs fast-framework-prompt --paper paper.pdf --out output/fast --deadline 180 --json
```

The fast path stops before image generation. It uses structured block-level PDF extraction, complete overview captions, stable page/content-hash evidence IDs, a semantic-only VLM request, evidence-gated generic contract completion, and separate document/contract caches. Layout, style, prompt, and editable overlays are compiled deterministically after the semantic graph. A warm paper normally completes in well under a second. If no VLM succeeds, the command returns an engineering result with explicit uncertainties instead of claiming production readiness.

Use `rfs inspect-pdf --paper paper.pdf --out output/inspection --json` to diagnose reading order, Unicode, OCR, section coverage, captions, parser agreement, and evidence-page coverage without model calls. Rotated native-text pages are transformed into displayed-page coordinates before ordering, and body text is conservatively classified as one, two, or three columns; spanning titles and captions remain explicit ordering boundaries. OCR lines use the same detector, including a three-to-two-column fallback for first pages where centered title fragments otherwise resemble a third column. Quality gates count all Unicode letters and numbers. English, Spanish, French, German, Portuguese, Chinese, Japanese, and Korean section aliases are recognized; localized `Figure/Table` prefixes and Chinese `图/表` captions are indexed. Caption prefixes must include a real numeric, Roman, or appendix identifier, so ordinary prose such as `figura editable` is not misclassified. CJK cross-extractor agreement uses character bigrams so per-character spacing differences do not resemble corruption. Cross-extractor quality uses directional lexical coverage while retaining order-sensitive agreement for diagnostics, preventing multi-column order differences, equation variables, and Poppler-only hidden text from causing wasteful OCR. The quality report exposes the maximum detected column count, the number of multi-column pages, and all rotated page numbers. For image-only/scanned papers, `--ocr-engine auto` prefers RapidOCR. Up to three selected pages run concurrently, and short narrow or vertical fragments in the outer page margins are removed as likely watermarks/page furniture. OCR candidates are scheduled by semantic signals first (overview figures, Method, Abstract, Conclusion), then by document-wide coverage anchors instead of simply taking the first six pages. `RFS_OCR_WORKERS` overrides page concurrency.

If a long fully scanned paper cannot reach the 60% full-document readability gate within the deadline, the workflow may continue only when at least six high-confidence sampled pages cover both Abstract and Method. The result records `semantic_scope: sampled_pages_only`, includes an explicit uncertainty about unprocessed pages, and can never be production-ready. Missing Abstract/Method coverage or weak OCR still stops semantic planning. EasyOCR downloads are opt-in through `RFS_OCR_ALLOW_DOWNLOAD=1`; missing models fail quickly and still write a complete extraction report.

Run all or selected paper benchmarks with aggregate reliability metrics:

```powershell
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/fast-suite --planner-mode heuristic --json
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/unseen --case-id 106_detr_set_prediction --case-id 107_clip_contrastive --json
rfs benchmark fast-suite --root benchmarks --out output/benchmarks/nlp --case-id 109_transformer_encoder_decoder --case-id 110_bert_pretrain_finetune --case-id 111_rag_retrieval_generation --planner-mode vlm --json
```

For OCR performance diagnosis, `extraction_report.json` and `benchmark pdf-suite` now record page rendering, text detection, orientation classification, text recognition, and post-processing time separately. RapidOCR defaults are deliberately conservative: detector limit `512`, recognition batch `6`, and an adaptive page-worker cap (4 on 8+ logical CPUs, 2 on 4-7, 1 below 4). Advanced local experiments can override these without changing repository defaults:

```powershell
$env:RFS_RAPIDOCR_DET_LIMIT = "512"
$env:RFS_RAPIDOCR_BATCH = "6"
$env:RFS_OCR_WORKERS = "3"
rfs benchmark pdf-suite --out output/benchmarks/pdf_profile --ocr-engine rapidocr --json
```

Lower detector limits are not assumed to be faster. On dense two-column scans, recognition usually dominates and smaller detector settings can have unstable latency; accept a change only after text agreement, section recovery, caption recovery, confidence, and wall-clock gates all pass.

Deadline-limited or failed OCR schedules are explicitly marked with `ocr_schedule_complete=false` / `ocr_run_complete=false`. Such document models are never written to the global document cache, and scientifically partial scan results are never written to the semantic contract cache; a transient slow or failed OCR run therefore cannot poison later fast runs.

When a deadline is active, every local OCR page runs in an isolated worker process. Completed pages are preserved, while workers still running at the reserved cutoff are terminated and recorded with `timed_out=true`. Single-page RapidOCR retains two intra-op threads; multi-page waves use one thread per worker. This prevents a slow ONNX recognition call from holding the fast workflow beyond its parsing budget or leaving background OCR processes behind.

For a fully scanned long paper with no native section signals, the six-page fallback schedule covers pages 1-4 first, then a page near 85% of the document and finally a middle page. Under a deadline, the first wave uses adaptive page concurrency; the two coverage-rescue pages run one at a time with two OCR threads whenever at least 45 seconds remain. This biases scarce OCR time toward the abstract, overview figure, early method details, and likely appendix/conclusion architecture evidence without weakening the hard cutoff.

In the 180-second fast path with `planner_mode=vlm`, rescue pages require at least 90 seconds remaining so the workflow can preserve a model-call and validation budget. Heuristic planning and PDF inspection retain the 45-second rescue threshold. The effective value is recorded as `ocr_rescue_min_remaining_seconds`.

Planner and review retries share one absolute provider deadline rather than receiving a fresh timeout per attempt. If the service is slow or unavailable, each request is clamped to the remaining budget, further retries stop at the cutoff, and any later semantic stage switches to the deterministic evidence-grounded fallback.

Born-digital and OCR-recovered pages also pass through a conservative repeated-margin filter. Short header or footer lines are removed only when the same digit-normalized pattern appears in the same margin on at least three pages and at least one quarter of the document. The report records `repeated_margin_noise_removed_count` so benchmark runs can detect publisher-header and page-number contamination without hiding the cleanup.

For pages carrying a PDF rotation flag, native blocks are ordered in the unrotated media-box coordinate system and only then transformed into displayed page coordinates. This preserves Abstract-to-Method-to-Figure reading order on 90/180/270-degree pages while keeping overlay coordinates aligned with rendered output.

Fast VLM planning preserves the paper's original writing system for every visible scientific label. Entity names and relation labels must either occur verbatim in their cited evidence or remain in the same source script; cross-script translations such as `文档编码器` to `Document encoder` fail planning validation and cannot be marked production-ready. Explanatory prose may follow the requested output language, but editable overlay labels do not.

For Spanish, French, German, and Portuguese papers, validation also detects same-script English translation. An English-looking visible label that does not occur verbatim anywhere in the paper evidence fails production validation even though both strings use Latin characters. This closes the gap where `codificador de documentos` could otherwise be silently changed to `Document Encoder`.

Relation labels are optional: if a model supplies a connector label that is not verbatim in the relation's cited evidence, normalization clears the label while preserving the grounded direction and type. Overlay compilation also emits an exact scientific label only once when the same evidence-backed concept is both a module and an innovation callout.

Native PDF lines split by publisher hyphenation are joined inside the same source text block before evidence IDs are created. Known scientific words such as `trans-` + `former` and `de-` + `coder` lose the layout-only hyphen, while unknown long compound parts retain a literal hyphen. The extraction report records `native_hyphenation_repair_count`.

OCR normalization also repairs fused numbered section boundaries such as `2方法`, `2Metodo`, `3Experimentos`, and `4Conclusion` before heading classification. The same rule covers common French, German, and Portuguese headings. English word segmentation now requires at least two scientific anchor words, preventing a single English-looking suffix from splitting valid non-English words such as Spanish `procesamiento`.

Production validation treats visible inputs, outputs, and innovations without evidence IDs as hard errors. Before validation, exact entity labels may be grounded deterministically to matching evidence; innovation labels are grounded only when the same evidence also contains an explicit novelty cue such as `we propose`, `we introduce`, or `本文提出`. Otherwise the result remains engineering-only instead of silently presenting an unsupported contribution.

Repeated-margin filtering interprets page edges in the PDF's semantic orientation. On a 90-degree page, the original header is detected at the displayed right edge and the original footer at the left edge; corresponding mappings are applied for 180 and 270 degrees. Mixed-orientation papers therefore use one header/footer signature space without leaking rotated publisher furniture into evidence.

Section headings are deduplicated only within their concrete page/block occurrence, not globally by title text. Repeated `Methods`, `Experiments`, or appendix headings therefore create new evidence boundaries after publisher headers have been removed.

PDF inputs receive a lightweight container preflight before pypdf, Poppler, or PyMuPDF extraction. Missing `%PDF-` headers and missing tail `%%EOF` markers return stable `ValueError` messages immediately; encrypted documents retain the explicit password-required error. This keeps `--json` failures concise and prevents damaged files from entering either cache.

When `benchmark pdf-suite` runs with a real OCR engine, it now includes fully rasterized two-column and 2-degree skewed two-column pages in addition to the mixed native/scan fixture. These cases enforce column reconstruction, left-column-first reading order, section recovery, caption recovery, and OCR confidence using the actual runtime engine.

RapidOCR pages render at 84 DPI by default. This retains the detector limit and recognition batch used by the fast path while recovering long Latin-script lines that could disappear at 72 DPI. The generated stress suite includes native and rasterized Spanish papers and records `render_dpi` for each OCR page; the current suite contains 10 parser-only cases and 16 cases with runtime OCR.

English OCR pages with at least two explicit English section anchors also receive a lexical plausibility check backed by the bundled word-frequency model. A known-word ratio below 0.72 raises a warning and below 0.50 fails extraction even when the OCR engine reports high confidence. The gate is not applied to CJK or unrecognized non-English Latin documents, preventing an English dictionary from rejecting unrelated languages.

Table captions now seed coordinate-based table regions. Header cells define column anchors, later cells are assigned by row and nearest column, and the document index stores `columns`, `rows`, `cells`, and a full table bounding box. Individual table cells are excluded from narrative evidence and replaced by one row-major structured table evidence record, preventing OCR detection order from turning `Model | Depth | Accuracy` into misleading prose.

Table reconstruction is intentionally conservative: a candidate needs a plausible labeled header and at least two data rows. Pure numeric rows and lowercase prose fragments such as `are | obtained` are rejected without changing the original block kinds, avoiding false table structure on captions, equations, and surrounding sentences.

If a deadline ends after at least three high-confidence scan pages have recovered both Abstract and Method-like evidence, the workflow continues with an engineering-grade partial contract instead of returning `extraction_failed`. It remains explicitly marked `sampled_pages_only` and `scientific_scope_complete=false`, is not eligible for production status, and cannot enter the semantic cache.

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
