# Benchmarks

Benchmarks are the product-level acceptance layer for paper-to-editable figure generation.

Each case should provide a paper, optional positive/negative visual references, a semantic expectation file, and expected production gates. Do not commit copyrighted papers or secrets; fixtures may point to locally supplied inputs.

Recommended benchmark dimensions:

- exact paper-label preservation
- entity and relation coverage
- connector endpoint correctness
- editability of text, panels, cards, and arrows
- visual similarity to the selected reference image
- PPTX package validity and preview rendering
- cross-machine execution with no repository-specific absolute paths
- API cost and elapsed time
