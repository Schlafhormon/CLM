# Monitoring Model

CLM monitoring is split into a small operator-oriented core and the existing
research/lab monitor.

## Core Monitoring

Core monitoring is the default product surface:

- HTTP probes for application readiness and client-visible availability;
- TCP probes for port-level reachability;
- command probes for explicit operator-provided app readiness checks;
- migration timeline events such as dump, transfer, restore, cutover and
  health/readiness markers;
- downtime windows derived from probe-visible outages;
- stable probe result events under schema `clm.monitoring.v1`;
- required vs optional app readiness semantics.

Required app readiness is fatal when a required probe fails or has no result.
Optional app readiness is reported as a warning and must not by itself turn a
successful restore or migration into a failed migration.

`clm run` starts core monitoring when monitoring is enabled. Without `--load`,
the generated runtime monitor command contains source/destination HTTP and TCP
health targets plus any explicit HTTP/TCP entries from `probes:`. VIP monitor
targets are added only when the effective traffic backend is `vip`, or when an
operator explicitly configures a VIP probe. External and command traffic modes
therefore do not imply VIP metrics.

The core summary fields are `status`, `core_status`, `core_downtime_ms`,
`core_downtime`, timeline/event markers, and the generic `http_downtime_ms` /
`l4_downtime_ms` values when available. Legacy VIP metrics may still be present
for compatibility, but they are no longer required for a normal run summary.

The code boundary for this model is `clm/monitoring/`:

- `probes.py` defines `ProbeSpec` for HTTP, TCP and command probes and validates
  config-style mappings.
- `events.py` defines `ProbeResult`, `ProbeEvent`, `TimelineEvent`,
  `DowntimeWindow` and `AppReadinessResult`.
- `legacy.py` translates current monitor CSV artifacts into stable probe
  results.

## Legacy Or Optional Monitoring

The existing `tools/monitor/monitor.py` remains the runtime monitor for now. It
also contains research-oriented functionality that should stay available but
not define the core monitoring model:

- info targets;
- counter targets;
- stream targets;
- download targets;
- upload targets;
- research batch analysis;
- paper-oriented plots and statistics.

These features are useful for experiments and troubleshooting. They should be
treated as optional analysis or legacy lab features, not as required CLM
operator functionality.

`clm run --load ...` keeps the legacy research monitor behavior compatible:
synthetic load profiles can add stream/download/upload monitor targets and
legacy info/counter targets. For a no-load migration, those targets are not
configured or started by default. Operators that need the old lab monitor
without a load profile can opt in with `monitor.enable_legacy_targets: true` or
`monitor.legacy_research_targets: true`.

## Compatibility

The current monitor is not rewritten in this step. New code should consume the
stable structures from `clm.monitoring` and use the parser/adapter layer for old
files such as:

- `<base>-http.csv`;
- `<base>-l4.csv`;
- `<base>-stream.ndjson`;
- `<base>-download.ndjson`;
- `<base>-upload.ndjson`.

Only HTTP and TCP CSV files are converted into core `ProbeResult` objects today.
Stream, download and upload files remain legacy analysis inputs.
