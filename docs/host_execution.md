# Host Execution

CLM now has a small host execution abstraction in `clm.host`.

## Current API

- `CommandResult`: command, exit code, stdout, stderr, duration, capture flag,
  and a sanitized string representation for logs.
- `CommandBuilder` / `ShellScript`: render validated environment exports and
  command lines for shell-script based host operations.
- `HostExecutor`: abstract execution interface.
- `LocalExecutor`: runs commands on the controller host.
- `SshExecutor`: runs remote scripts through SSH with `bash -l -s`, sending the
  script on stdin instead of embedding it in a remote shell command argument.
- `clm.host.deployment`: minimal host artifact deployment for script-based
  operations.

`SshExecutor` intentionally does not create remote directories, copy files,
remove files, synchronize repositories, or perform cleanup. Those operations
must stay in higher-level orchestration or future explicit storage/helper
backends.

## Deployment Modes

Host execution now separates command transport from script deployment.

`execution.deployment_mode` controls how script-based runc operations find CLM
host scripts:

- `artifact_deploy`: the controller selects the scripts needed for the current
  operation, creates a temporary remote working directory, copies those scripts
  into `<workdir>/scripts`, sets `REPO=<workdir>`, runs the script from there,
  and removes only that generated temporary workdir after successful execution.
- `legacy_repo`: compatibility mode. The old `repo_path` contract remains in
  effect, so Source/Destination must have a CLM checkout at `repo_path`, and
  scripts run as `bash "$REPO/scripts/..."`.

The default config path is `artifact_deploy`. Operators can pin the old
behavior in YAML:

```yaml
execution:
  deployment_mode: legacy_repo
```

or override it for one command:

```bash
clm preflight --env config/env.yaml --method precopy --deployment-mode legacy_repo
clm run --env config/env.yaml --method precopy --deployment-mode artifact_deploy
```

## Artifact Deploy Semantics

The first deployment scope is intentionally small:

- runc migration deploys only the selected migration wrapper and its current
  legacy implementation script;
- runc source baseline reset deploys only
  `restore_runc_bundle_baseline.sh` and `patch_runc_bundle_for_criu.sh`;
- deployment uses SSH command stdin plus base64 file payloads;
- remote files are placed under `execution.remote_temp_root` (default `/tmp`)
  in a generated `clm-*` directory;
- safe cleanup removes only that generated temp directory, only after success,
  and only if its parent is the configured temp root and its basename starts
  with `clm-`.

Riskier cleanup actions such as deleting container state, network state, shared
container directories, or destination-local container directories remain governed
by explicit cleanup policy and are not enabled by artifact deployment.

## Preflight Semantics

Preflight is mode-specific:

- `legacy_repo` checks the monitor repo, Source/Destination repo presence, and
  Git HEAD synchronization across monitor/source/dest.
- `artifact_deploy` checks controller-side script availability, SSH reachability,
  remote tempdir creation/removal, deployment tooling (`bash`, `base64`,
  `mktemp`, `chmod`), runtime tooling, storage, sudo, ports, and CRIU. It does
  not check Source/Destination repo presence or Git HEAD.

## Legacy CLI Helpers

The following functions in `clm.cli` are compatibility adapters and should not
be used by new code:

- `run_local`
- `run_shell_local`
- `run_remote`

They keep the old patch points and return shape stable while delegating to
`LocalExecutor` or `SshExecutor`.

The old `_escape_env_value`, `_export_lines`, and `build_remote_script` helper
names also remain as compatibility wrappers around `CommandBuilder`.

The following streaming helpers are still legacy implementations:

- `_run_local_streamed`
- `_run_remote_streamed`

They remain in `clm.cli` for now because they own progress-aware streaming
output and keep the legacy call surface stable.

See `docs/shell_execution_risks.md` for the current Python-side risk
reductions and the remaining legacy Bash risks.
