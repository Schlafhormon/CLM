"""Command-based traffic backend."""

from __future__ import annotations

import shlex
from typing import Any, Callable, Mapping, Optional

from clm.core.models import PreflightResult, TrafficPlan
from clm.host import CommandResult, HostExecutor, LocalExecutor
from clm.migration.traffic.base import (
    TrafficActionResult,
    TrafficBackend,
    TrafficConfigError,
    noop_result,
)


class CommandTrafficBackend(TrafficBackend):
    """Run operator-provided command hooks for traffic phases.

    Hook commands are argv lists by default. Shell strings are rejected unless
    the hook or backend explicitly sets ``allow_shell: true``.
    """

    mode = "command"
    actions = ("prepare", "switch", "verify", "rollback")

    def __init__(
        self,
        plan: Optional[TrafficPlan] = None,
        *,
        executor: Optional[HostExecutor] = None,
        logger: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(plan=plan or TrafficPlan(mode=self.mode))
        self.executor = executor or LocalExecutor()
        self.logger = logger

    def preflight(self, context: Optional[Mapping[str, Any]] = None) -> PreflightResult:
        checks = []
        blockers = []
        for action in self.actions:
            try:
                command = self._normalize_hook(action)
            except TrafficConfigError as exc:
                blockers.append(str(exc))
                checks.append({"name": f"traffic command {action}", "ok": False, "detail": str(exc)})
                continue
            detail = self._display_command(command) if command is not None else "not configured"
            checks.append({"name": f"traffic command {action}", "ok": True, "detail": detail})
        return PreflightResult(checks=tuple(checks), blockers=tuple(blockers), metadata={"mode": self.mode})

    def prepare(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return self._run_hook("prepare")

    def switch(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return self._run_hook("switch")

    def verify(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return self._run_hook("verify")

    def rollback(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return self._run_hook("rollback")

    def script_env(self, config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        env: dict[str, Any] = {"TRAFFIC_MODE": self.mode}
        for action in self.actions:
            command = self._normalize_hook(action)
            if command is not None:
                env[f"TRAFFIC_{action.upper()}_CMD"] = self._script_command(command)
        return env

    def _run_hook(self, action: str) -> TrafficActionResult:
        command = self._normalize_hook(action)
        if command is None:
            return noop_result(action, f"traffic command {action} hook not configured")
        self._log(f"traffic command {action}: {self._display_command(command)}")
        if isinstance(command, str):
            result = self.executor.run(["bash", "-lc", command], capture=True, check=False)
        else:
            result = self.executor.run(command, capture=True, check=False)
        return self._action_result(action, result)

    def _normalize_hook(self, action: str) -> list[str] | str | None:
        if action not in self.actions:
            raise TrafficConfigError(f"unsupported traffic hook action: {action}")
        hooks = self.plan.hooks or {}
        raw = hooks.get(action)
        if raw in (None, "", False):
            return None

        allow_shell_default = _as_bool(self.plan.options.get("allow_shell", False))
        if isinstance(raw, dict):
            cfg = dict(raw)
            raw_command = cfg.get("command", cfg.get("cmd"))
            allow_shell = _as_bool(cfg.get("allow_shell", allow_shell_default))
        else:
            raw_command = raw
            allow_shell = allow_shell_default

        if isinstance(raw_command, str):
            if not allow_shell:
                raise TrafficConfigError(
                    f"traffic hook {action} is a shell string; use argv list or set allow_shell: true"
                )
            _reject_control_chars(raw_command, action)
            return raw_command

        if isinstance(raw_command, (list, tuple)):
            command = [str(part) for part in raw_command]
            if not command or not command[0]:
                raise TrafficConfigError(f"traffic hook {action} command must not be empty")
            for part in command:
                _reject_control_chars(part, action)
            return command

        raise TrafficConfigError(f"traffic hook {action} command must be a list or allowed shell string")

    def _script_command(self, command: list[str] | str) -> str:
        if isinstance(command, str):
            return command
        return shlex.join(command)

    def _display_command(self, command: list[str] | str) -> str:
        if isinstance(command, str):
            return CommandResult(command=command, exit_code=0).command_display
        return CommandResult(command=command, exit_code=0).command_display

    def _action_result(self, action: str, result: CommandResult) -> TrafficActionResult:
        ok = result.returncode == 0
        message = f"traffic command {action} exited rc={result.returncode}"
        return TrafficActionResult(
            action=action,
            ok=ok,
            skipped=False,
            message=message,
            returncode=result.returncode,
            details={
                "command": result.command_display,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_s": result.duration_s,
            },
        )

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger(message)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _reject_control_chars(value: str, action: str) -> None:
    if any(ord(ch) < 32 for ch in value):
        raise TrafficConfigError(f"traffic hook {action} contains control characters")
