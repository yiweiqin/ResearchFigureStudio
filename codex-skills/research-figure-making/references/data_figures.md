# Data Figures

## Summary

Use this route for result plots, ablation studies, statistical figures, benchmark
comparisons, trend plots, heatmaps, distribution plots, calibration plots, and
multi-panel experimental figures.

## Principle

Data figures must be reproducible. Use Python for computation, aggregation,
statistical tests, and base plotting. Use PPTX as the default editable assembly
layer for layout, annotations, panel assembly, and visual polish.

## Figure Selection

Choose the plot from the paper claim:

- comparison across methods: grouped bar, dot plot, slope plot, critical
  difference plot
- trend over scale or time: line plot with uncertainty, small multiples
- ablation: ordered bars, waterfall-style contribution, connected dot plot
- distribution: violin, boxen, ridgeline, ECDF, histogram with density
- matrix relationship: heatmap, clustered heatmap, confusion matrix
- qualitative examples: table-like panel with compact callouts, not a dense chart
- uncertainty or robustness: interval plot, bootstrap confidence bands, raincloud

Avoid defaulting to bar charts when ranking, distribution, or effect size would
communicate the paper's claim more clearly.

## Plotting Standards

- Use consistent typography across panels and exports.
- Use colorblind-safe palettes and avoid rainbow maps unless the data is cyclic
  or the field convention requires it.
- Show uncertainty where relevant: confidence intervals, standard error, standard
  deviation, bootstrap intervals, or explicit run count.
- Use direct labels when they reduce legend lookup.
- Keep legends outside data-dense regions.
- Use units and metric definitions on axes or captions.
- Sort categories by meaningful order: paper order, metric value, taxonomy, or
  experimental progression.
- For dense labels, rotate only as a last resort; prefer wrapping, abbreviation,
  small multiples, or horizontal layout.

## Export Requirements

Generate at least:

- `.py` plotting script
- cleaned or derived `.csv` when source data needs transformation
- `editable_composition.pptx` for final editable assembly when the data plot is
  part of a paper figure or PPT figure
- `.pdf` and/or `.svg` only when vector export or embedding is needed
- `.png` at 300-600 DPI for quick review

For image-heavy multi-panel figures, export the final composition at 600 DPI.

## PPT Editing Route

- For simple bars, lines, scatter plots, and small tables, prefer native PPT
  charts or editable PPT shapes when values can be represented faithfully.
- For heatmaps, networks, dense statistical plots, or plots requiring precise
  Python rendering, export the Python plot as PDF/SVG/PNG, insert it into PPT,
  then add titles, annotations, significance marks, panel IDs, and captions as
  editable PPT objects.
- Do not manually alter plotted values in PPT. If values change, regenerate the
  Python plot and update the inserted asset.

## Quality Checks

Before final delivery:

- check label overlap and clipping
- check legend overlap
- check axis unit clarity
- check tick density
- check small-font readability after single-column or double-column scaling
- verify plotted values against the source table or data file
- verify that any statistical annotation has a known test and sample count

If a plot looks sparse or uninformative, improve the information design before
changing colors: add uncertainty, effect sizes, meaningful grouping, direct
labels, small multiples, or a better chart type.
