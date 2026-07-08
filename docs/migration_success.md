# Migration Success Contract

This page defines the operator-facing contract for deciding whether a CLM run
succeeded, partially succeeded, or failed. It describes the result artifacts
operators should inspect first and how to interpret known legacy gaps.

## Status Vocabulary

CLM uses these operator-facing states:

| State | Meaning |
|---|---|
| `ok` | Runtime migration restored the container on the destination, required verification passed, monitoring/analysis completed when enabled, and cleanup either succeeded or was explicitly skipped. |
| `partial` | The destination restore is known or assumed to have succeeded, but a post-restore concern failed: traffic switch/verify, monitoring/analysis, or cleanup. The migrated workload may need operator attention even though the restore path completed. |
| `failed` | The runtime migration did not complete, or a required probe failed or produced no successful result. The destination should not be treated as the new healthy serving location without manual validation. |
| `aborted` | The run was interrupted before normal completion. Treat as failed until manually inspected. |
| `running` | The run has started and no final contract can be inferred yet. |
| `unknown` | Required result fields are missing or unreadable. Treat as not successful. |

`clm.analysis.summary.summarize_run_dir()` derives the same high-level view from
`status.json` and `summary.json`. It keeps `status.json` as the primary runtime
status, but can mark a failed legacy return code as `partial` when structured
artifacts prove restore succeeded and a post-restore action failed.

## Decision Order

Operators and automation should use this order:

1. If `status.json.status` is `aborted` or `running`, that is the primary run
   state.
2. If any required app/readiness probe is fatal, the run is `failed`, even when
   restore returned successfully.
3. If `status.json.status` is `failed` and there is no structured evidence that
   restore completed before a post-restore failure, the run is `failed`.
4. If runtime restore failed, the run is `failed`.
5. If restore succeeded but traffic switch or traffic verify failed, the run is
   `partial`.
6. If restore and required probes succeeded but monitoring or analysis failed,
   the run is `partial`.
7. If restore, required probes, and traffic succeeded but cleanup failed, the
   run is `partial`.
8. Only when none of the failure or partial conditions apply is the run `ok`.

## Required Cases

### Runtime Migration Successful

Runtime migration is successful when the runtime backend returns success:

- `MigrationResult.status` is `ok`, `success`, or `succeeded`, or
  `MigrationResult.ok` is true.
- For the current legacy `clm run` path, `run_migration(...)` returned `0` and
  final `status.json.status` is `ok`.
- Expected artifacts are present: `status.json`, `summary.json` when monitoring
  was enabled, `events/events.ndjson` when events were emitted, and
  `migrate/<method>.log`.

This is necessary but not always sufficient for overall `ok`; traffic,
required probes, analysis, and cleanup can still make the operator outcome
`partial` or `failed`.

### Restore Successful But Traffic Or Verify Failed

If destination restore completed but the configured traffic backend could not
switch or verify client-facing traffic, classify the operator outcome as
`partial`.

Relevant fields:

- `status.json.phases.restore` with `ok: true`, `status: ok`, or
  `completed: true` confirms that destination restore completed.
- `status.json.traffic` or `status.json.phases.traffic` with `ok: false`,
  `status: failed`, `failed_action: switch` or `failed_action: verify`, or a
  non-zero action `returncode` identifies the post-restore traffic failure.
- `summary.json.traffic`, `summary.json.traffic_verify`, or equivalent backend
  action result with `ok: false`, failed `status`, or non-zero `returncode`.
- Event evidence such as restore completion followed by traffic failure
  markers, when available.
- `MigrationResult.phases`, `MigrationResult.traffic`, and
  `MigrationResult.artifacts` fields such as `returncode`, `events_log`, and
  `migrate_log` for script-level diagnosis.

Current legacy runc scripts are still VIP-oriented. Some traffic failures may
surface only as a non-zero migration return code, in which case
`status.json.status` may remain `failed`; `clm.analysis.summary` reclassifies
the operator outcome as `partial` when the artifacts show restore success plus
traffic or verify failure.

### Required Probe Failed

Required probes are part of the success contract. A required probe that fails or
has no successful result makes the run `failed`.

Relevant fields:

- App readiness payloads such as `app_readiness`, `readiness`, or
  `required_probe`.
- `status.json.probe_readiness` or `status.json.phases.probe_readiness`.
- `fatal: true`.
- `required: true` with `ready: false`.
- Non-empty `failed_required` or `missing_required`.

Optional probe failures are warnings. They do not by themselves change a
successful runtime migration to `failed`.

### Monitoring Or Analysis Failed

Monitoring and analysis failures do not mean the runtime migration failed. If
the runtime path is `ok` but monitoring or analysis failed, classify the
operator outcome as `partial`.

Relevant fields:

- `status.json.monitor_enabled`.
- `status.json.analyze_rc`; non-zero means analysis failed.
- `summary.json.status: error` or `failed`.
- `summary.json.message`, `summary.json.errors`, and `monitor/analyze.log`.

If monitoring was explicitly disabled, `summary.json.status: skipped` with
`reason: monitoring_disabled` is not a failure by itself.

### Cleanup Failed

Cleanup happens after the migration decision. Cleanup failure is operationally
important but does not undo a successful restore. If the runtime path is `ok`
and cleanup fails, classify the operator outcome as `partial`.

Relevant fields:

- `status.json.cleanup` and `meta/cleanup.json`.
- Nested cleanup action fields: `attempted`, `ok`, `error`, `path`, and
  `policy`.
- `status.json.no_cleanup`; explicit skip is not a failure.

## Decisive Fields

### `status.json`

Use these fields first:

- `status`: primary legacy run status: `running`, `ok`, `failed`, or `aborted`.
- `error`: primary failure message for runtime or orchestration failure.
- `start_ts`, `end_ts`: run duration source when summary durations are absent.
- `monitor_enabled`: whether monitor/analysis artifacts are expected.
- `migrate_enabled`, `control_run`: distinguish real migration from
  monitor-only control runs.
- `analyze_rc`: analysis result code; non-zero after runtime `ok` means
  `partial`.
- `phases`, `traffic`, `probe_readiness`: structured backend result details
  copied from `MigrationResult` when the runtime adapter can provide them.
- `cleanup`: cleanup outcome; failed nested actions after runtime `ok` mean
  `partial`.
- `no_cleanup`: explicit cleanup skip; not a failure by itself.

### `summary.json`

Use these fields for operator summary and verification:

- `status`: analyzer status. It is secondary to `status.json.status` for the
  runtime decision.
- `core_status`, `core_summary.status`: normalized operator-facing summary
  status where present.
- `core_downtime_ms`, `downtime_ms`, `http_downtime_ms`, `l4_downtime_ms`, and
  VIP downtime fields for availability interpretation.
- `analyze_rc`, `message`, `errors`: analysis health and diagnostics.
- `migration_params.traffic_mode`: whether the run used `external`, `command`,
  or legacy `vip` traffic assumptions.
- App readiness/probe result blocks such as `app_readiness` or `readiness`.
- Traffic action blocks such as `traffic`, `traffic_verify`, or `verify`.
- Artifact pointers such as `events`, `base_out`, and `core_summary.artifact_paths`.

### `MigrationResult`

Runtime and strategy backends should populate:

- `migration_id`: stable run identifier.
- `status`: backend result status; `ok`, `success`, or `succeeded` means
  `MigrationResult.ok` is true.
- `started_at`, `ended_at`, `timings`: timing and duration source.
- `downtime_ms`: direct downtime when known by the backend.
- `errors`: backend or strategy errors.
- `warnings`: non-fatal concerns such as legacy adapter use.
- `phases`: structured phase outcomes keyed by phase name. Current common keys
  are `runtime`, `script`, `checkpoint`, `transfer`, `restore`,
  `probe_readiness`, and `traffic`.
- `traffic`: structured traffic backend outcome with `mode`, `status`, `ok`,
  `returncode`, optional `failed_action`, and per-action details under
  `actions.prepare`, `actions.switch`, and `actions.verify`.
- `probe_readiness`: structured required readiness/probe result where the
  runtime has such a gate.
- `artifacts`: paths and diagnostic data, especially `events_log`,
  `migrate_log`, `returncode`, selected strategy/backend metadata, and transfer
  mode details.

Backends should prefer explicit structured fields over encoding restore,
traffic, probe, or cleanup state only in log text.

## Current Legacy Limits

The current Python CLI still delegates the implemented runtime migration to
legacy runc scripts. Those scripts keep VIP cutover as a strong assumption in
some paths. Docker and containerd backends fail fast before migration. For
`clm run`, the capability gate must run before run directories, cleanup/reset,
monitoring, synthetic load, and migration side effects.

`traffic.mode=external` and `traffic.mode=command` are supported as
non-VIP handoff modes for the current runc adapter. They do not export `VIP_*`
script environment, and the Bash `TRAFFIC_MODE` branches for these modes must
not run VIP address, conntrack, or arping commands. The scripts still contain
VIP helper functions for the `vip` compatibility branch.

The runc legacy adapter now records `returncode`, traffic mode, restore
markers, traffic action markers, and postcopy destination readiness markers
when they are present in the events log. The Bash scripts still abort through
shared shell error handling and do not always emit an explicit
`traffic_*_failed` or `restore_failed` event. When only a non-zero return code
is available and no restore/traffic markers were emitted, CLM must keep the run
as `failed`. Inspect `events/events.ndjson` and the migration log to determine
whether destination restore completed before traffic or verification failed.
