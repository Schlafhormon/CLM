# Host Execution

CLM now has a small host execution abstraction in `clm.host`.

## Current API

- `CommandResult`: command, exit code, stdout, stderr, duration, capture flag,
  and a sanitized string representation for logs.
- `HostExecutor`: abstract execution interface.
- `LocalExecutor`: runs commands on the controller host.
- `SshExecutor`: builds and runs SSH commands with `bash -lc` on a remote host.

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

The following streaming helpers are still legacy implementations:

- `_run_local_streamed`
- `_run_remote_streamed`

They remain in `clm.cli` for now because they own progress-aware streaming
output and still return `subprocess.CompletedProcess`.
