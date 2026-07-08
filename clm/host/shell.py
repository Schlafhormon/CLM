"""Shell script and SSH command rendering helpers."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)="
    r"(?:'[^']*'|\"[^\"]*\"|[^\s;]+)"
)
_SECRET_FLAG_EQ_RE = re.compile(
    r"(?i)(--(?:password|passwd|secret|token|api-key|access-key)="
    r")(?:'[^']*'|\"[^\"]*\"|[^\s;]+)"
)
_SECRET_FLAG_SPACE_RE = re.compile(
    r"(?i)(--(?:password|passwd|secret|token|api-key|access-key)\s+)"
    r"(?:'[^']*'|\"[^\"]*\"|[^\s;]+)"
)
_EXPORT_SECRET_RE = re.compile(
    r"(?im)^(export\s+[A-Za-z_][A-Za-z0-9_]*(?:PASSWORD|PASSWD|PWD|SECRET|TOKEN|API_KEY|APIKEY|ACCESS_KEY|ACCESSKEY)[A-Za-z0-9_]*=)"
    r".*$"
)


ShellCommand = str | Sequence[str | Path]


def shell_quote(value: Any, *, expand_home: bool = True) -> str:
    """Quote a value for Bash assignment or argv rendering."""

    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "1" if value else "0"
    else:
        text = str(value)

    if expand_home and text.startswith("~/"):
        return "${HOME}" + shlex.quote(text[1:])
    return shlex.quote(text)


def render_env_exports(env_vars: Mapping[str, Any]) -> str:
    """Render validated Bash export statements."""

    lines: list[str] = []
    for name, value in env_vars.items():
        key = str(name)
        if not _ENV_NAME_RE.fullmatch(key):
            raise ValueError(f"invalid shell environment variable name: {key!r}")
        lines.append(f"export {key}={shell_quote(value)}")
    return "\n".join(lines)


def render_shell_command(command: ShellCommand) -> str:
    if isinstance(command, str):
        return command
    return shlex.join(str(part) for part in command)


def sanitize_command_display(command: str, max_len: int = 500) -> str:
    """Redact common secret forms from command/script display strings."""

    text = _EXPORT_SECRET_RE.sub(r"\1<redacted>", command)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _SECRET_FLAG_EQ_RE.sub(r"\1<redacted>", text)
    text = _SECRET_FLAG_SPACE_RE.sub(r"\1<redacted>", text)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _target(host: str, user: str | None = None) -> str:
    return f"{user}@{host}" if user else host


@dataclass(frozen=True)
class ShellScript:
    """A Bash script assembled from safe exports and command lines."""

    env: Mapping[str, Any] = field(default_factory=dict)
    commands: tuple[ShellCommand, ...] = ()
    strict: bool = True

    def export_lines(self) -> str:
        return render_env_exports(self.env)

    def command_lines(self) -> str:
        return "\n".join(render_shell_command(command) for command in self.commands)

    def render(self) -> str:
        parts: list[str] = []
        if self.strict:
            parts.append("set -euo pipefail")
        exports = self.export_lines()
        if exports:
            parts.append(exports)
        commands = self.command_lines()
        if commands:
            parts.append(commands)
        return "\n".join(parts) + "\n"

    @property
    def display(self) -> str:
        return sanitize_command_display(self.render())


@dataclass(frozen=True)
class RemoteScript:
    """Description of running a shell script on a host through SSH."""

    host: str
    script: ShellScript | str
    user: str | None = None
    port: int | None = None
    connect_timeout: int = 5
    strict_host_key_checking: str = "accept-new"
    extra_options: tuple[str, ...] = ()
    bash_args: tuple[str, ...] = ("bash", "-l", "-s")

    @property
    def target(self) -> str:
        return _target(self.host, self.user)

    @property
    def script_text(self) -> str:
        if isinstance(self.script, ShellScript):
            return self.script.render()
        return str(self.script)

    def ssh_argv(self) -> list[str]:
        args = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={int(self.connect_timeout)}",
            "-o",
            f"StrictHostKeyChecking={self.strict_host_key_checking}",
        ]
        if self.port is not None:
            args.extend(["-p", str(self.port)])
        args.extend(self.extra_options)
        args.extend([self.target, "--", *self.bash_args])
        return args

    @property
    def display(self) -> str:
        header = shlex.join(self.ssh_argv()) + " <<'CLM_SCRIPT'"
        return sanitize_command_display(f"{header}\n{self.script_text}\nCLM_SCRIPT")


class CommandBuilder:
    """Factory for shell script and remote SSH command descriptions."""

    @staticmethod
    def shell_script(
        env_vars: Mapping[str, Any] | None = None,
        commands: Sequence[ShellCommand] | None = None,
        *,
        strict: bool = True,
    ) -> ShellScript:
        return ShellScript(env=dict(env_vars or {}), commands=tuple(commands or ()), strict=strict)

    @staticmethod
    def remote_script(
        host: str,
        script: ShellScript | str,
        *,
        user: str | None = None,
        port: int | None = None,
        connect_timeout: int = 5,
        strict_host_key_checking: str = "accept-new",
        extra_options: Sequence[str] | None = None,
    ) -> RemoteScript:
        return RemoteScript(
            host=host,
            script=script,
            user=user,
            port=port,
            connect_timeout=connect_timeout,
            strict_host_key_checking=strict_host_key_checking,
            extra_options=tuple(extra_options or ()),
        )
