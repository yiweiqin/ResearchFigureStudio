# Paper To Figure

## Summary

Use this reference before drawing. The goal is to turn the user's paper into a
figure plan without importing generic model assumptions.

## Extraction Pass

Read enough of the paper to fill these fields:

- paper type: method, benchmark, dataset, application, analysis, survey, system
- central claim: the one-sentence point the figure should help prove
- research objects: models, datasets, tasks, agents, modules, variables, metrics
- method flow: inputs, transformations, intermediate states, outputs
- train/test split: training-only steps, inference-only steps, offline/online steps
- experimental logic: baselines, settings, ablations, metrics, comparisons
- terminology: exact names used by the paper for key concepts

If a field is missing, mark it as unknown instead of inventing it.

## Figure Inventory

Create a short list of figures the paper actually needs:

- **Figure 1 / overview**: method story, system pipeline, or conceptual overview
- **Architecture figure**: internal model, agent, or algorithm components
- **Data construction figure**: collection, filtering, annotation, synthesis, split
- **Main result figure**: strongest empirical comparison or trend
- **Ablation figure**: which component matters and why
- **Case study figure**: input/output example, qualitative behavior, error pattern
- **Appendix figure**: extra mechanism or data detail not needed in the main text

For each candidate, write:

- figure purpose
- source sections or tables
- information payload
- suggested format
- whether it belongs in main paper, appendix, slides, or should be skipped

Skip figures that only decorate the paper.

## Framework Figure Brief

Before generating images, produce a brief:

- paper-derived modules, using the paper's names
- visual metaphor for each module
- scientific relationship between modules
- flow direction and grouping
- which labels must be editable text
- which elements may be AI-generated imagery
- target format: single-column, double-column, full-width, or slide

The brief should be specific enough that image prompts do not need to invent the
system structure.

## Data Figure Brief

Before plotting, produce a brief:

- data source files or tables
- x/y variables, grouping, uncertainty, metric units
- comparison being made
- expected visual form and why
- paper claim supported by the plot
- any statistical tests or confidence intervals required

Do not plot from prose-only numbers unless the user confirms the values or the
values can be extracted reliably from a table.
