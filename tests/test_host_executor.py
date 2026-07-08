#!/usr/bin/env python3

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from clm.host import CommandResult, LocalExecutor, ProcessHandle, SshExecutor


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


class _FakePopenProcess:
    def __init__(self, returncode=0, lines=None):
        self.returncode = returncode
        self.stdout = _FakeStdout(lines or [])

    def wait(self):
        return self.returncode


class _FakeBackgroundProcess:
    def __init__(self):
        self.pid = 4242
        self.returncode = None
        self.signals = []
        self.terminated = False
        self.killed = False
        self.wait_timeout = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_timeout = timeout
        self.returncode = 0
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class LocalExecutorTests(unittest.TestCase):
    def test_run_capture_returns_result_with_output_exit_code_and_duration(self):
        result = LocalExecutor().run(
            [sys.executable, "-c", "print('hello')"],
            capture=True,
            check=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "hello")
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.captured)
        self.assertGreaterEqual(result.duration_s, 0.0)

    def test_run_non_capture_redirects_to_given_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.txt"
            with out_path.open("w", encoding="utf-8") as fp:
                result = LocalExecutor().run(
                    [sys.executable, "-c", "print('direct')"],
                    stdout=fp,
                    check=True,
                )

            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.captured)
            self.assertIsNone(result.stdout)
            self.assertEqual(out_path.read_text(encoding="utf-8").strip(), "direct")

    def test_run_check_raises_called_process_error_with_captured_output(self):
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            LocalExecutor().run(
                [sys.executable, "-c", "import sys; print('bad'); sys.exit(9)"],
                capture=True,
                check=True,
            )

        self.assertEqual(ctx.exception.returncode, 9)
        self.assertIn("bad", ctx.exception.output)

    def test_run_streamed_forwards_lines_and_returns_captured_output(self):
        calls = {}

        def fake_popen(command, **kwargs):
            calls["command"] = command
            calls["kwargs"] = kwargs
            return _FakePopenProcess(lines=["one\n", "two\n"])

        streamed = []
        result = LocalExecutor(popen_factory=fake_popen).run_streamed(
            ["tool", "arg"],
            check=True,
            on_output=streamed.append,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "one\ntwo\n")
        self.assertEqual(streamed, ["one\n", "two\n"])
        self.assertTrue(result.captured)
        self.assertEqual(calls["command"], ["tool", "arg"])
        self.assertEqual(calls["kwargs"]["stderr"], subprocess.STDOUT)

    def test_run_streamed_check_raises_with_captured_output(self):
        def fake_popen(command, **kwargs):
            return _FakePopenProcess(returncode=23, lines=["failure\n"])

        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            LocalExecutor(popen_factory=fake_popen).run_streamed(["tool"], check=True)

        self.assertEqual(ctx.exception.returncode, 23)
        self.assertIn("failure", ctx.exception.output)

    def test_start_returns_process_handle_and_passes_background_options(self):
        calls = {}
        fake_process = _FakeBackgroundProcess()

        def fake_popen(command, **kwargs):
            calls["command"] = command
            calls["kwargs"] = kwargs
            return fake_process

        result = LocalExecutor(popen_factory=fake_popen).start(
            ["tool", "token=abc123"],
            stdout="out",
            stderr="err",
            text=False,
            cwd="/tmp",
            env={"A": "B"},
        )

        self.assertIsInstance(result, ProcessHandle)
        self.assertIs(result.process, fake_process)
        self.assertEqual(result.pid, 4242)
        self.assertEqual(result.args, ["tool", "token=abc123"])
        self.assertEqual(calls["command"], ["tool", "token=abc123"])
        self.assertEqual(calls["kwargs"]["stdout"], "out")
        self.assertEqual(calls["kwargs"]["stderr"], "err")
        self.assertFalse(calls["kwargs"]["text"])
        self.assertEqual(calls["kwargs"]["cwd"], "/tmp")
        self.assertEqual(calls["kwargs"]["env"], {"A": "B"})

        result.send_signal(2)
        self.assertEqual(fake_process.signals, [2])
        self.assertEqual(result.wait(timeout=3), 0)
        self.assertEqual(fake_process.wait_timeout, 3)
        self.assertEqual(result.poll(), 0)
        result.terminate()
        result.kill()
        self.assertTrue(fake_process.terminated)
        self.assertTrue(fake_process.killed)

    def test_process_handle_string_redacts_secrets(self):
        fake_process = _FakeBackgroundProcess()
        handle = ProcessHandle(["tool", "--password", "open-sesame"], fake_process)

        text = str(handle)

        self.assertIn("--password <redacted>", text)
        self.assertNotIn("open-sesame", text)


class CommandResultTests(unittest.TestCase):
    def test_string_representation_redacts_command_and_omits_output_contents(self):
        result = CommandResult(
            command=["tool", "--password", "open-sesame", "token=abc123"],
            exit_code=1,
            stdout="very sensitive output",
            stderr="very sensitive error",
            duration_s=0.1234,
            captured=True,
        )

        text = str(result)
        self.assertIn("--password <redacted>", text)
        self.assertIn("token=<redacted>", text)
        self.assertIn("exit_code=1", text)
        self.assertIn("stdout_len=21", text)
        self.assertNotIn("open-sesame", text)
        self.assertNotIn("very sensitive output", text)


class SshExecutorTests(unittest.TestCase):
    def test_build_command_wraps_script_in_bash_lc_without_connecting(self):
        executor = SshExecutor("example.org", user="clm", port=2222)
        command = executor.build_command("echo hello && uname -a")

        self.assertEqual(command[0], "ssh")
        self.assertIn("BatchMode=yes", command)
        self.assertIn("ConnectTimeout=5", command)
        self.assertIn("StrictHostKeyChecking=accept-new", command)
        self.assertIn("-p", command)
        self.assertIn("2222", command)
        self.assertEqual(command[-3], "clm@example.org")
        self.assertEqual(command[-2], "--")
        self.assertTrue(command[-1].startswith("bash -lc "))
        self.assertIn("echo hello", command[-1])

    def test_run_uses_built_ssh_command_with_fake_runner(self):
        calls = {}

        def fake_runner(command, **kwargs):
            calls["command"] = command
            calls["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, 0, stdout="remote-out", stderr="")

        executor = SshExecutor("host1", runner=fake_runner)
        result = executor.run("printf hi", capture=True, check=True)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "remote-out")
        self.assertEqual(calls["command"][0], "ssh")
        self.assertEqual(calls["command"][-3], "host1")
        self.assertEqual(calls["kwargs"]["stdout"], subprocess.PIPE)
        self.assertEqual(calls["kwargs"]["stderr"], subprocess.PIPE)

    def test_run_streamed_uses_built_ssh_command_and_streams_output(self):
        calls = {}

        def fake_popen(command, **kwargs):
            calls["command"] = command
            calls["kwargs"] = kwargs
            return _FakePopenProcess(lines=["remote-one\n", "remote-two\n"])

        streamed = []
        executor = SshExecutor("host1", popen_factory=fake_popen)
        result = executor.run_streamed("printf hi", check=True, on_output=streamed.append)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "remote-one\nremote-two\n")
        self.assertEqual(streamed, ["remote-one\n", "remote-two\n"])
        self.assertEqual(calls["command"][0], "ssh")
        self.assertEqual(calls["command"][-3], "host1")
        self.assertEqual(calls["command"][-2], "--")
        self.assertTrue(calls["command"][-1].startswith("bash -lc "))
        self.assertIn("printf hi", calls["command"][-1])
        self.assertEqual(calls["kwargs"]["stderr"], subprocess.STDOUT)

    def test_start_uses_built_ssh_command_without_connecting(self):
        calls = {}
        fake_process = _FakeBackgroundProcess()

        def fake_popen(command, **kwargs):
            calls["command"] = command
            calls["kwargs"] = kwargs
            return fake_process

        executor = SshExecutor("host1", popen_factory=fake_popen)
        result = executor.start("printf hi", stdout="out", stderr="err", text=False)

        self.assertIsInstance(result, ProcessHandle)
        self.assertEqual(calls["command"][0], "ssh")
        self.assertEqual(calls["command"][-3], "host1")
        self.assertTrue(calls["command"][-1].startswith("bash -lc "))
        self.assertEqual(calls["kwargs"]["stdout"], "out")
        self.assertEqual(calls["kwargs"]["stderr"], "err")
        self.assertFalse(calls["kwargs"]["text"])

    def test_streamed_result_redacts_secrets_from_ssh_command_display(self):
        def fake_popen(command, **kwargs):
            return _FakePopenProcess(lines=["ok\n"])

        result = SshExecutor("host1", popen_factory=fake_popen).run_streamed(
            "deploy token=abc123 --password open-sesame",
            check=True,
        )

        text = str(result)
        self.assertIn("token=<redacted>", text)
        self.assertIn("--password <redacted>", text)
        self.assertNotIn("abc123", text)
        self.assertNotIn("open-sesame", text)

    def test_remote_cwd_and_env_are_explicitly_not_implemented(self):
        executor = SshExecutor("host1", runner=lambda command, **kwargs: None)

        with self.assertRaises(NotImplementedError):
            executor.run("pwd", cwd="/tmp")

        with self.assertRaises(NotImplementedError):
            executor.run("env", env={"A": "B"})

        with self.assertRaises(NotImplementedError):
            executor.run_streamed("pwd", cwd="/tmp")

        with self.assertRaises(NotImplementedError):
            executor.run_streamed("env", env={"A": "B"})


if __name__ == "__main__":
    unittest.main()
