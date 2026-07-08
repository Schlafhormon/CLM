# CLM Configuration

CLM has two config tracks during the refactor:

- `config/env.example.yaml` is the legacy config consumed by the current CLI.
- `config/clm.example.yaml` is the draft v1 config for the future operator
  workflow.

The v1 config is modeled around `MigrationRequest` and the new runtime,
storage, traffic, probe, cleanup, and output boundaries. It is not a complete
execution contract yet.

## Top-Level Shape

`version` must be `1`. The file describes one migration request:

- `source`: host where the container currently runs.
- `destination`: host where the container should be restored.
- `monitor`: optional host that runs monitoring/probes.
- exactly one of `container` or `container_group`.
- `runtime`, `criu`, `strategy`, `storage`, `traffic`, `probes`, `cleanup`,
  and `output` describe how the request should be planned and reported.

Host entries accept `host`, `ip`, `user`, `port`, and `execution`. `execution`
is currently descriptive; `local` means no SSH should be needed for that role,
while `ssh` means CLM should use remote execution.

## Runtime

`runtime.type` selects the container runtime backend. `runc` is the only backend
that can currently execute migrations through the legacy scripts. `docker` and
`containerd` are represented as preflight/inspect skeletons and should fail
fast for migration execution until their backends are implemented.

Privilege mode is explicit:

- `privilege_mode: rootful` and `rootless: false` describe the current common
  CRIU/runc path.
- `privilege_mode: rootless` and `rootless: true` document rootless intent.

Rootless migration remains dependent on runtime, kernel, namespace, storage,
and CRIU support. The config can express it before CLM can guarantee every
combination.

## Container Scope

Use `container` for a single container. Important fields are:

- `id`: runtime container identifier.
- `image`: source image or descriptive image reference.
- `bundle_path`: OCI/runc bundle path when the runtime needs one.
- `namespace` and `project`: runtime or platform scoping metadata.

Use `container_group` instead of `container` for multi-container migrations.
Groups can be ordered and can declare dependency names. Group execution
semantics are still a schema decision; the current models can represent the
request, but orchestration is not implemented.

## CRIU

`criu.binary` is the executable CLM should call. This can point to a system CRIU
or a custom build, for example `/opt/criu-clm/sbin/criu`.

`criu.custom_build` records provenance such as build name, repository, commit,
or build directory. It is metadata for now; the binary path remains the
execution source of truth.

`criu.features` lists expected feature support such as `tcp-established` or
`lazy-pages`. Future preflight should compare these requirements with the
actual CRIU binary and fail with actionable diagnostics.

## Strategy

`strategy.mode` accepts:

- `auto`: conservative default, currently equivalent to `stop-and-copy`.
- `stop-and-copy`: safest baseline strategy.
- `pre-copy`: lower downtime path using iterative checkpointing.
- `post-copy`: lazy-pages path, currently advanced/experimental.

`experimental_minimal_downtime` is an explicit opt-in for automatic selection
to prefer lower-downtime modes later. Today automatic selection should stay
conservative unless a strategy is requested directly.

## Storage

`storage.mode` accepts:

- `shared`: source and destination can both see the checkpoint root, typically
  an NFS mount such as `/mnt/criu`.
- `rsync`: CLM-managed transfer path from source-visible checkpoint storage to
  destination storage.

Shared storage is implemented in the current runc legacy path. Rsync is modeled
for planning/preflight, but the legacy migration scripts do not execute rsync
transfer yet.

Important fields:

- `share_root`: common checkpoint root for shared storage.
- `runs_root` and `logs_root`: generated run and log roots.
- `destination_root`: destination-local CRIU cache/root.
- `image_mode`: restore from `shared` images or use a destination-local copy
  where supported.

## Traffic

`traffic.mode` accepts:

- `external`: CLM does not switch traffic. It can still run a verify hook.
- `none`: alias for `external`.
- `command`: CLM runs operator-provided prepare, switch, verify, and rollback
  hooks.
- `vip`: legacy lab-oriented VIP/GARP/conntrack behavior.

Command hooks should be argv lists:

```yaml
traffic:
  mode: command
  hooks:
    prepare: [lbctl, drain, source.example.net]
    switch: [lbctl, activate, dest.example.net]
    verify: [curl, -fsS, http://service.example.net/health]
```

Shell strings are rejected by the command backend unless `allow_shell: true` is
set explicitly.

## Probes

`probes` define app readiness and optional verification. Supported types are:

- `http`: requires `url`; supports `expected_statuses`.
- `tcp`: requires `host` and `port`.
- `command`: requires `command` argv.

`required: true` means readiness failure should be fatal for the app-readiness
success condition. Optional probes can still produce warnings and diagnostics.

## Cleanup

Cleanup is safe by default:

- `shared_images_policy` and `local_images_policy` accept `success_only`,
  `always`, or `never`.
- risky cleanup actions, such as container state or network state cleanup,
  require `risky_actions_enabled: true` or explicit action names under
  `explicit_risky_actions`.

## Output

`output` describes desired artifacts:

- concise console summary;
- structured JSON result;
- event log;
- optional Markdown or HTML report;
- artifact root for raw logs and runtime data.

The current models store this section as request options. Exact path templating
and report generation semantics are still open.

## Draft Parser Helpers

`clm.core.config` contains lightweight helpers for the v1 draft:

- `load_clm_v1(path)`;
- `validate_clm_v1_config(config)`;
- `load_clm_v1_migration_request(path)`;
- `clm_v1_to_migration_request(config)`.

These helpers validate obvious shape errors and build core dataclasses. They
are not a final JSON Schema replacement.
