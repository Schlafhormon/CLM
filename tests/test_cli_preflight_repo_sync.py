#!/usr/bin/env python3


import unittest
import io
import tempfile
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import clm.cli as cli


class CliPreflightRepoSyncTests(unittest.TestCase):
    def test_parse_git_head_valid_and_invalid(self):
        good = "a" * 40
        self.assertEqual(cli._parse_git_head(f"{good}\n"), good)
        self.assertIsNone(cli._parse_git_head("not-a-hash"))
        self.assertIsNone(cli._parse_git_head("abc123"))

    def test_repo_sync_result_ok_when_all_heads_equal(self):
        head = "b" * 40
        ok, detail = cli._repo_sync_check_result(
            {"monitor": head, "source": head, "dest": head},
            {},
        )
        self.assertTrue(ok)
        self.assertEqual(detail, "commit=" + head[:12])

    def test_repo_sync_result_fails_on_mismatch(self):
        ok, detail = cli._repo_sync_check_result(
            {"monitor": "a" * 40, "source": "b" * 40, "dest": "a" * 40},
            {},
        )
        self.assertFalse(ok)
        self.assertIn("monitor=aaaaaaaaaaaa", detail)
        self.assertIn("source=bbbbbbbbbbbb", detail)
        self.assertIn("dest=aaaaaaaaaaaa", detail)

    def test_repo_sync_result_fails_on_missing_or_errors(self):
        ok, detail = cli._repo_sync_check_result(
            {"monitor": "a" * 40},
            {"source": "ssh failed", "dest": "repo fehlt"},
        )
        self.assertFalse(ok)
        self.assertIn("monitor=aaaaaaaaaaaa", detail)
        self.assertIn("source=ERR:ssh failed", detail)
        self.assertIn("dest=ERR:repo fehlt", detail)

    def test_preflight_artifact_deploy_skips_remote_repo_git_heads(self):
        cfg = deepcopy(cli.DEFAULTS)
        stdout = io.StringIO()
        remote_scripts = []

        def fake_run_remote(host, script, **kwargs):
            remote_scripts.append(script)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            with patch("clm.cli.run_shell_local", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), \
                 patch("clm.cli.run_remote", side_effect=fake_run_remote), \
                 redirect_stdout(stdout):
                rc = cli.preflight(cfg, method="precopy")

        self.assertEqual(rc, 0)
        out = stdout.getvalue()
        self.assertIn("execution: deployment mode artifact_deploy", out)
        self.assertIn("controller: deployment scripts available", out)
        self.assertIn("source: deploy temp dir", out)
        self.assertIn("dest: deploy temp dir", out)
        self.assertIn("skipped for deployment_mode=artifact_deploy", out)
        combined = "\n".join(remote_scripts)
        self.assertNotIn("git rev-parse", combined)
        self.assertNotIn("test -d \"${HOME}/CLM\"", combined)

    def test_preflight_legacy_repo_keeps_repo_sync_checks(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["execution"]["deployment_mode"] = "legacy_repo"
        cfg["repo_path"] = "."
        head = "c" * 40
        stdout = io.StringIO()
        remote_scripts = []

        def fake_run_shell_local(script, **kwargs):
            if "git rev-parse" in script:
                return SimpleNamespace(returncode=0, stdout=head + "\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run_remote(host, script, **kwargs):
            remote_scripts.append(script)
            if "git rev-parse" in script:
                return SimpleNamespace(returncode=0, stdout=head + "\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            with patch("clm.cli.run_shell_local", side_effect=fake_run_shell_local), \
                 patch("clm.cli.run_remote", side_effect=fake_run_remote), \
                 redirect_stdout(stdout):
                rc = cli.preflight(cfg, method="precopy")

        self.assertEqual(rc, 0)
        out = stdout.getvalue()
        self.assertIn("execution: deployment mode legacy_repo", out)
        self.assertIn("repo: git commit synchron", out)
        combined = "\n".join(remote_scripts)
        self.assertIn("git rev-parse --verify HEAD", combined)


if __name__ == "__main__":
    unittest.main()
