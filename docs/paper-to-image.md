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

Resume a failed candidate with one localized repair instead of generating a new
initial batch:

```powershell
rfs paper-to-image `
  --paper "C:\path\paper.pdf" `
  --out "output\paper_to_image_repair" `
  --planner-mode vlm `
  --asset-mode image2 `
  --review-mode vlm `
  --repair-source "output\paper_to_image\candidates\candidate_01.png" `
  --repair-rounds 1 `
  --image-retries 0 `
  --ocr-engine off `
  --json
```

`--repair-source` skips fresh initial candidate generation. The source is first
reviewed against the current exact-label and scientific contract. If it fails,
the best source is edited once and reviewed again. The request manifest marks
the reused source separately from the real Image2 repair request.

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

Built-in templates include `dense-multiframe`, `multimodal`, `branch`,
`feedback`, `arbor`, `linear`, `tripanel`, and `dense-multimodal`. Dense
task/model/data-engine overviews with nested local flows use `dense-multiframe`;
multi-input systems that converge through a modality encoder bank into one joint
space use `multimodal`; compact iterative
generation/feedback/refinement systems use `feedback`; shared-trunk systems with
parallel output heads use `branch`; true search-tree systems use `arbor`.
Positive references are classified into
the closest ratio-based reference archetype and become
content-free profiles containing normalized panels, topology, connector rhythm,
density, palette, and forbidden copied content. Automatic selection uses module
count, loop/tree/parallel-branch structure, multimodality, retrieval structure,
and requested ratio.

The selected profile is rendered as `layout_blueprint.png` and is the only image
supplied to Image2 edit for initial candidates. Reference-derived profiles remain
free of copied reference text and reference-specific objects.

For supported normalized topologies (`linear`, `branch`, `multimodal`,
`feedback`, and `dense_multiframe`), contracts with 2-16 visible entities are
compiled into `layout_blueprint.json.semantic_plan`. The plan records exact
paper labels, normalized node boxes, graph ranks, distinct source/target ports,
relation types, connector labels, multi-point paths, and route styles. The
generic compiler:

- puts independent inputs in one layer and separates their fan-in ports;
- keeps parallel branch outputs in one layer with separate fan-out ports;
- moves source-only conditioning nodes immediately before their target;
- routes skip-layer edges around intermediate nodes instead of through them;
- routes backward/feedback edges through an outer canvas lane;
- refuses to force more than 16 visible nodes into one raster guide.

When the contract matches a stricter built-in topology, the renderer uses a
specialized semantic layout instead:

- `feedback`: the forward generation chain, two independent inputs to refinement,
  the self-feedback node, and the return loop terminating at feedback;
- `dense-multiframe`: task/model/data-engine panels, separate image and prompt
  encoder paths, decoder-to-mask output, the data-engine stage chain, and a
  separate model-to-data-engine support arrow.

This semantic blueprint is still generated from the evidence-backed contract;
it does not copy paper figures or invent labels. It reduces topology drift by
making Image2 preserve an explicit scientific source of truth instead of
inferring node mapping from empty placeholder boxes.

Entity roles are part of that source of truth. Data sources, modalities,
processing modules, innovations, and outputs are reviewed separately even when
all their words are present. Explicit provenance text is normalized into a
source-to-modality-to-method chain, and multiple named sources may be collapsed
into one evidence-backed source group to avoid redundant nodes and crossed
edges. Explicit internal/external evaluation boundaries and named paper methods
or techniques are repaired deterministically when overview evidence states
them.

Image-2 candidates must enrich the semantic blueprint rather than merely
restyling its boxes. Candidate review records `blueprint_enrichment_ratio` and
`blueprint_mean_abs_difference`; production defaults require at least `0.08`
changed-pixel enrichment inside the blueprint's detected active figure region.
Reports also retain `blueprint_global_enrichment_ratio`,
`blueprint_active_region_bbox`, and `blueprint_active_region_fraction` for
diagnosis. This keeps the threshold strict without penalizing feedback or
branch layouts that intentionally leave large white margins. The VLM aesthetic review separately scores visual
information density, mechanism visualization, and publication polish. Sparse
text-only nodes therefore fail even when labels, arrows, spacing, and colors
are otherwise correct.

For branch figures, evidence-backed parallel leaf heads are normalized to the
same output-head role. Relations from an upstream ancestor directly into one
head are removed when they bypass the shared branch point already feeding that
head. If an innovation label is identical to an existing module or output, the
role contract highlights the existing node rather than requesting a duplicate.
For nested feedback layouts, the deterministic blueprint starts the feedback-to-
refinement connector at the inner feedback artifact, not the outer container
boundary.

The same generic semantic plan can now bypass raster generation entirely:

```powershell
rfs fast-framework-prompt `
  --paper paper.pdf `
  --out output\fast_result `
  --editable-ppt
```

This writes `figure_program.json` and `editable_composition.pptx`. Nodes are
native PowerPoint shapes with exact editable labels; multi-segment routes and
feedback loops are native connectors created behind the nodes. The compiler
also writes `semantic_ppt_report.json` and records every editable node and
connector in `composition_quality_report.json`. The same provenance contract is
used here, so data sources feed their declared modalities instead of appearing
as peer sensor inputs.

Before semantic layout, contract completion prefers true early model-overview
figures over late scaling, timing, attention, or visualization figures. It also
removes isolated appendix-only diagram labels, innovations that cannot be
grounded to novelty evidence, duplicate aliases such as `MLP`/`MLP Head`, and
input shortcuts that bypass an explicit intermediate representation.

The general production review and focused topology review execute concurrently.
Their default request timeout is 90 seconds with no automatic retry, preventing
two independent judges from creating a multi-minute sequential stall. Configure
`RFS_PAPER_TO_IMAGE_REVIEW_TIMEOUT` and
`RFS_PAPER_TO_IMAGE_TOPOLOGY_TIMEOUT` when a slower provider requires a larger
budget. Existing candidates can be passed through `--repair-source` so review or
localized repair does not regenerate the correct parts of the image.

Image-2 edit requests default to a 120-second timeout controlled by
`RFS_IMAGE2_TIMEOUT`. Network timeouts stop the candidate immediately instead of
blindly regenerating the entire image. Retryable HTTP or provider failures may
retry up to `--image-retries`; the default is one.

## Stability Audit

Production stability requires repeated independent candidates rather than a
single selected best image. Run at least three candidates:

```powershell
rfs paper-to-image `
  --paper paper.pdf `
  --out output/stability `
  --asset-mode image2 `
  --review-mode vlm `
  --candidates 3 `
  --repair-rounds 0
```

The workflow writes `stability_report.json` with `seed_count`,
`production_pass_rate`, `mean_score`, `worst_case_score`,
`standard_deviation`, per-candidate scores, and failure-mode counts. Repair
candidates and reused `--repair-source` images are excluded because they are not
independent generations. `rfs benchmark score` consumes the generated report
automatically.

The review gate also rejects `unexpected_labels`: visible scientific labels
outside `figure_specification.required_labels` and `repeatable_labels`. This is
stricter than checking hallucinations alone because a term can be supported by
the paper yet still be outside the intended overview contract.

The focused topology judge also supports explicit containment semantics. If a
declared operation container visibly contains an evidence-supported repeatable
shared component, an arrow from that nested component to the target may satisfy
the container's outgoing relation. This is limited to repeatable labels inside
the declared source container; it cannot excuse missing cross-panel arrows,
shortcuts, reversed edges, or invented nodes.

If a stability run is interrupted or one provider request fails, resume it in
place:

```powershell
rfs paper-to-image `
  --paper paper.pdf `
  --out output/stability `
  --candidates 3 `
  --resume-candidates
```

Existing `candidate_XX.png` files are re-reviewed with the current gates and
only missing candidates are generated. A three-seed stability run also permits
one bounded replacement for a provider-failed seed; successful candidates are
never regenerated by that replacement path.

When `--aspect-ratio auto` is used, the template keeps its internal normalized
geometry while the generation canvas uses the nearest native Image2 ratio
(`3:2`, `2:3`, or `1:1`). This avoids semantic cropping after generation.

## Production Gates

Every Image2 candidate must pass:

- exact-label OCR with no missing, misspelled, duplicate, or copied reference labels;
- scientific module and relation checks with no invention or reversal;
- for feedback, branch, multimodal, and dense layouts, a second focused topology
  review that verifies visible connector endpoints and arrowheads, rejects
  bypasses, and writes `topology_critic_report.json`;
- template alignment score of at least `0.70` with no copied reference content;
- aesthetic score of at least `0.70`;
- valid image resolution and blueprint aspect ratio.

Scientific score must be at least `0.95`; OCR must be exact. If three candidates fail, the best candidate receives one localized Image2 edit repair. If the repair still fails, the command stops without writing `selected_image.png`.

## Engineering Mode

`--asset-mode placeholder --planner-mode heuristic --review-mode heuristic` validates contracts without API cost. It writes `engineering_preview.png`, never `selected_image.png`, and is not production eligible.
