# Analysis Split

CLM now has an explicit analysis boundary:

- `clm.analysis.summary` is core-facing and dependency-light. It extracts the
  concise migration summary fields that operators need by default: status,
  duration, downtime, errors, and artifact paths.
- `clm.analysis.advanced` is the optional compatibility namespace for the
  existing batch, statistics, and plot pipeline.
- `clm.analysis_pipeline` remains import-compatible for existing scripts and
  tests, but new call sites should prefer `clm.analysis.advanced` for heavy
  analysis helpers.

The long-term direction is to keep one-run summaries and raw artifact links in
the core migration path, while moving batch evaluation, research metrics,
bootstrap statistics, paper views, and plot generation out of the required CLM
core. Those features remain useful for lab work and troubleshooting, but they
should become an optional install extra or separate package namespace.

## Core Summary Inputs

`summarize_run_dir(<run_dir>)` reads known run artifacts when present:

- `summary.json` or `monitor/summary.json`
- `status.json` or `meta/run.json`
- `events.ndjson` or `monitor/events.ndjson`
- `monitor/`
- `analysis/`

`build_core_summary(...)` can also consume a mapping or a
`MigrationResult`-like object directly.

## Remaining Split Work

- Move the implementation currently in `clm.analysis_pipeline` into smaller
  modules under `clm.analysis.advanced` or an optional package.
- Keep only stable summary and raw-artifact parsing APIs on the core import
  path.
- Define packaging extras such as `analysis` and `plots` once dependencies are
  split.
- Move paper-specific configs and research plot presets out of default
  configuration.
