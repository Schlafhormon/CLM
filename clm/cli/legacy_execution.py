"""Legacy shell execution helpers."""

from __future__ import annotations

from .legacy_run import (
    LocalExecutor,
    SshExecutor,
    _bash_dquote_escape,
    _escape_env_value,
    _export_lines,
    _run_local_streamed,
    _run_remote_streamed,
    build_remote_script,
    is_local_host,
    run_local,
    run_remote,
    run_shell_local,
)

__all__ = (
    "LocalExecutor",
    "SshExecutor",
    "_bash_dquote_escape",
    "_escape_env_value",
    "_export_lines",
    "_run_local_streamed",
    "_run_remote_streamed",
    "build_remote_script",
    "is_local_host",
    "run_local",
    "run_remote",
    "run_shell_local",
)
