# Enhancement Pipeline

## Summary

Use this reference when AI-generated visual blocks need higher resolution,
cleaner edges, background removal, safe background extension, or artifact repair.

## Allowed Enhancement

Enhancement may improve:

- resolution
- edge crispness
- antialiasing
- mild texture clarity
- transparent or clean backgrounds
- pure-background trim, padding, and aspect ratio consistency

Enhancement must not change:

- scientific structure
- relationship between modules
- labels, formulas, numbers, axes, or symbols
- object identity when it affects interpretation

If an image block is scientifically wrong, regenerate it instead of repairing it.
If an image block has too much whitespace, regenerate or reprompt first. Only
trim pure background when no semantic subject, card edge, character, icon, or
scientific cue is touched.

## Tool Routing

- **Real-ESRGAN**: default local super-resolution path when installed or easy to
  install. Prefer 2x or 4x. Use tiling for large images.
- **Upscayl**: default GUI-friendly local option built around Real-ESRGAN models.
- **Topaz Gigapixel**: optional paid tool for manual final enhancement.
- **Background removal / segmentation**: use when blocks need transparent
  placement in PPT/SVG. Keep extracted edges clean and avoid losing fine details.
- **Image editing tools**: use only for local cleanup, not for inventing missing
  scientific content.

## Artifact Naming

Keep a reversible chain:

- `block-01_prompt.md`
- `block-01_raw.png`
- `block-01_upscaled.png`
- `block-01_cutout.png`
- `block-01_final.png`
- `framework_editable.pptx` or equivalent
- `framework_review.png`
- `framework_submission.pdf` or `framework_submission_600dpi.png`

## Review Rules

Inspect each enhanced block at:

- native size
- expected PPT size
- expected paper single-column or double-column size

Reject blocks with hallucinated letters, fake axes, pseudo-code, fake UI, or
ambiguous scientific symbols. Mask or crop non-critical artifacts only if the
scientific meaning remains unchanged.
