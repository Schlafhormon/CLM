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

`SshExecutor` intentionally does not create remote directories, copy files,
remove files, synchronize repositories, or perform cleanup. Those operations
must stay in higher-level orchestration or future explicit storage/helper
backends.

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
