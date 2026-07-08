#!/usr/bin/env python3

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from clm.host import CommandResult, LocalExecutor, SshExecutor


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

    def test_remote_cwd_and_env_are_explicitly_not_implemented(self):
        executor = SshExecutor("host1", runner=lambda command, **kwargs: None)

        with self.assertRaises(NotImplementedError):
            executor.run("pwd", cwd="/tmp")

        with self.assertRaises(NotImplementedError):
            executor.run("env", env={"A": "B"})


if __name__ == "__main__":
    unittest.main()
