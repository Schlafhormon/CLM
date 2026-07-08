"""Host command execution abstractions.

The executors in this module are intentionally small adapters around process
execution. They do not copy code to remote hosts, create remote directories, or
perform cleanup. Higher orchestration layers decide what should run.
"""

from __future__ import annotations

import abc
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from clm.host.shell import CommandBuilder, RemoteScript, sanitize_command_display


Command = str | Sequence[str | Path]
Runner = Callable[..., subprocess.CompletedProcess]
PopenFactory = Callable[..., subprocess.Popen]
StreamCallback = Callable[[str], None]


def _command_to_display(command: Command) -> str:
    if isinstance(command, str):
        text = command
    else:
        text = shlex.join(str(part) for part in command)
    return _sanitize_command(text)


def _sanitize_command(command: str, max_len: int = 500) -> str:
    return sanitize_command_display(command, max_len=max_len)


@dataclass(frozen=True)
class CommandResult:
    """Result of running a command on a host.

    ``returncode`` and ``args`` mirror ``subprocess.CompletedProcess`` enough
    for the current CLI compatibility adapters.
    """

    command: Command
    exit_code: int
    stdout: Any = None
    stderr: Any = None
    duration_s: float = 0.0
    captured: bool = False
    display: Optional[str] = None

    @property
    def returncode(self) -> int:
        return self.exit_code

    @property
    def args(self) -> Command:
        return self.command

    @property
    def command_display(self) -> str:
        if self.display is not None:
            return _sanitize_command(self.display)
        return _command_to_display(self.command)

    def check_returncode(self) -> None:
        if self.exit_code != 0:
            raise subprocess.CalledProcessError(
                self.exit_code,
                self.command,
                output=self.stdout,
                stderr=self.stderr,
            )

    def __str__(self) -> str:
        stdout_len = len(self.stdout) if self.stdout is not None else 0
        stderr_len = len(self.stderr) if self.stderr is not None else 0
        return (
            "CommandResult("
            f"command={self.command_display!r}, "
            f"exit_code={self.exit_code}, "
            f"duration_s={self.duration_s:.3f}, "
            f"captured={self.captured}, "
            f"stdout_len={stdout_len}, "
            f"stderr_len={stderr_len}"
            ")"
        )


@dataclass(frozen=True)
class ProcessHandle:
    """Handle for a background process started through a host executor."""

    command: Command
    process: subprocess.Popen
    display: Optional[str] = None

    @property
    def args(self) -> Command:
        return self.command

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def returncode(self) -> Optional[int]:
        return self.process.returncode

    @property
    def command_display(self) -> str:
        if self.display is not None:
            return _sanitize_command(self.display)
        return _command_to_display(self.command)

    def poll(self) -> Optional[int]:
        return self.process.poll()

    def wait(self, timeout: Optional[float] = None) -> int:
        return self.process.wait(timeout=timeout)

    def send_signal(self, sig: int) -> None:
        self.process.send_signal(sig)

    def terminate(self) -> None:
        self.process.terminate()

    def kill(self) -> None:
        self.process.kill()

    def __str__(self) -> str:
        return (
            "ProcessHandle("
            f"command={self.command_display!r}, "
            f"pid={self.pid}, "
            f"returncode={self.returncode}"
            ")"
        )


class HostExecutor(abc.ABC):
    """Abstract command runner for one execution host."""

    @abc.abstractmethod
    def run(
        self,
        command: Command,
        *,
        check: bool = False,
        capture: bool = False,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        stdout: Any = None,
        stderr: Any = None,
        text: bool = True,
    ) -> CommandResult:
        raise NotImplementedError

    @abc.abstractmethod
    def run_streamed(
        self,
        command: Command,
        *,
        check: bool = False,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        on_output: Optional[StreamCallback] = None,
        text: bool = True,
    ) -> CommandResult:
        raise NotImplementedError

    @abc.abstractmethod
    def start(
        self,
        command: Command,
        *,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        stdout: Any = None,
        stderr: Any = None,
        text: bool = True,
    ) -> ProcessHandle:
        raise NotImplementedError


class LocalExecutor(HostExecutor):
    """Run commands on the local controller host."""

    def __init__(self, runner: Runner = subprocess.run, popen_factory: PopenFactory = subprocess.Popen):
        self._runner = runner
        self._popen_factory = popen_factory

    def run(
        self,
        command: Command,
        *,
        check: bool = False,
        capture: bool = False,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        stdout: Any = None,
        stderr: Any = None,
        text: bool = True,
    ) -> CommandResult:
        run_stdout = subprocess.PIPE if capture else stdout
        run_stderr = subprocess.PIPE if capture else stderr
        start = time.monotonic()
        proc = self._runner(
            command,
            check=False,
            stdout=run_stdout,
            stderr=run_stderr,
            text=text,
            cwd=cwd,
            env=env,
        )
        duration = time.monotonic() - start
        result = CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout=getattr(proc, "stdout", None),
            stderr=getattr(proc, "stderr", None),
            duration_s=duration,
            captured=capture,
        )
        if check:
            result.check_returncode()
        return result

    def run_shell(self, script: str, **kwargs: Any) -> CommandResult:
        return self.run(["bash", "-lc", script], **kwargs)

    def run_streamed(
        self,
        command: Command,
        *,
        check: bool = False,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        on_output: Optional[StreamCallback] = None,
        text: bool = True,
    ) -> CommandResult:
        start = time.monotonic()
        proc = self._popen_factory(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=text,
            bufsize=1,
            cwd=cwd,
            env=env,
        )
        captured = []
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    captured.append(line)
                    if on_output is not None:
                        on_output(line)
            rc = proc.wait()
        finally:
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

        stdout_text = "".join(captured)
        result = CommandResult(
            command=command,
            exit_code=rc,
            stdout=stdout_text,
            stderr=None,
            duration_s=time.monotonic() - start,
            captured=True,
        )
        if check:
            result.check_returncode()
        return result

    def start(
        self,
        command: Command,
        *,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        stdout: Any = None,
        stderr: Any = None,
        text: bool = True,
    ) -> ProcessHandle:
        proc = self._popen_factory(
            command,
            stdout=stdout,
            stderr=stderr,
            text=text,
            cwd=cwd,
            env=env,
        )
        return ProcessHandle(command=command, process=proc)


class SshExecutor(HostExecutor):
    """Run shell scripts on a remote host through SSH."""

    def __init__(
        self,
        host: str,
        *,
        user: Optional[str] = None,
        port: Optional[int] = None,
        connect_timeout: int = 5,
        strict_host_key_checking: str = "accept-new",
        extra_options: Optional[Sequence[str]] = None,
        runner: Runner = subprocess.run,
        popen_factory: PopenFactory = subprocess.Popen,
    ):
        self.host = host
        self.user = user
        self.port = port
        self.connect_timeout = int(connect_timeout)
        self.strict_host_key_checking = strict_host_key_checking
        self.extra_options = tuple(extra_options or ())
        self._runner = runner
        self._popen_factory = popen_factory

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def build_command(self, command: Command) -> list[str]:
        return self._remote_script(command).ssh_argv()

    def _remote_script(self, command: Command) -> RemoteScript:
        script = command if isinstance(command, str) else shlex.join(str(part) for part in command)
        return CommandBuilder.remote_script(
            self.host,
            script,
            user=self.user,
            port=self.port,
            connect_timeout=self.connect_timeout,
            strict_host_key_checking=self.strict_host_key_checking,
            extra_options=self.extra_options,
        )

    def run(
        self,
        command: Command,
        *,
        check: bool = False,
        capture: bool = False,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        stdout: Any = None,
        stderr: Any = None,
        text: bool = True,
    ) -> CommandResult:
        if cwd is not None:
            raise NotImplementedError("SshExecutor cwd handling is not implemented yet")
        if env is not None:
            raise NotImplementedError("SshExecutor remote env handling is not implemented yet")
        remote = self._remote_script(command)
        ssh_command = remote.ssh_argv()
        run_stdout = subprocess.PIPE if capture else stdout
        run_stderr = subprocess.PIPE if capture else stderr
        start = time.monotonic()
        proc = self._runner(
            ssh_command,
            check=False,
            stdout=run_stdout,
            stderr=run_stderr,
            text=text,
            input=remote.script_text if text else remote.script_text.encode(),
        )
        result = CommandResult(
            command=ssh_command,
            exit_code=proc.returncode,
            stdout=getattr(proc, "stdout", None),
            stderr=getattr(proc, "stderr", None),
            duration_s=time.monotonic() - start,
            captured=capture,
            display=remote.display,
        )
        if check:
            result.check_returncode()
        return result

    def run_streamed(
        self,
        command: Command,
        *,
        check: bool = False,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        on_output: Optional[StreamCallback] = None,
        text: bool = True,
    ) -> CommandResult:
        if cwd is not None:
            raise NotImplementedError("SshExecutor cwd handling is not implemented yet")
        if env is not None:
            raise NotImplementedError("SshExecutor remote env handling is not implemented yet")
        remote = self._remote_script(command)
        ssh_command = remote.ssh_argv()
        start = time.monotonic()
        proc = self._popen_factory(
            ssh_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=text,
            bufsize=1,
        )
        stdin = getattr(proc, "stdin", None)
        if stdin is not None:
            stdin.write(remote.script_text if text else remote.script_text.encode())
            stdin.close()
        captured = []
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    captured.append(line)
                    if on_output is not None:
                        on_output(line)
            rc = proc.wait()
        finally:
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

        result = CommandResult(
            command=ssh_command,
            exit_code=rc,
            stdout="".join(captured),
            stderr=None,
            duration_s=time.monotonic() - start,
            captured=True,
            display=remote.display,
        )
        if check:
            result.check_returncode()
        return result

    def start(
        self,
        command: Command,
        *,
        cwd: Optional[str | Path] = None,
        env: Optional[Mapping[str, str]] = None,
        stdout: Any = None,
        stderr: Any = None,
        text: bool = True,
    ) -> ProcessHandle:
        if cwd is not None:
            raise NotImplementedError("SshExecutor cwd handling is not implemented yet")
        if env is not None:
            raise NotImplementedError("SshExecutor remote env handling is not implemented yet")
        remote = self._remote_script(command)
        ssh_command = remote.ssh_argv()
        proc = self._popen_factory(
            ssh_command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            text=text,
        )
        stdin = getattr(proc, "stdin", None)
        if stdin is not None:
            stdin.write(remote.script_text if text else remote.script_text.encode())
            stdin.close()
        return ProcessHandle(ssh_command, process=proc, display=remote.display)
