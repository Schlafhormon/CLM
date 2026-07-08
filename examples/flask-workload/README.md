# Flask Workload Example

The current implementation still lives at `workload/flask_app/` for
compatibility with legacy `clm run --load ...` profiles.

This directory marks the intended future example location. A later refactor
can move the Flask app here once scripts, docs, config examples, and tests no
longer assume the old `workload/` path.

Use this workload only for synthetic migration experiments. For normal
migrations, omit `--load` and let CLM migrate the configured container without
starting built-in load generators.
