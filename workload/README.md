# Legacy Workload Assets

This directory contains the Flask workload extracted from the original
research setup. It is kept in place for compatibility with existing
`clm run --load ...` profiles and tests.

The normal migration path should not depend on this directory. Run CLM without
`--load` for ordinary migrations; use application probes or external traffic
generation instead.

Planned transition:

- keep `workload/flask_app/` working while legacy tests and scripts still
  reference it;
- document the example under `examples/flask-workload/`;
- move or duplicate only when the CLI/tests have been adjusted to avoid a
  broad compatibility break.
