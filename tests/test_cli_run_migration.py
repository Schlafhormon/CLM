#!/usr/bin/env python3


import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import yaml

from clm import cli


class RunMigrationTests(unittest.TestCase):
    def _run_cli_expect_capability_gate(self, cfg, *, method="precopy"):
        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")
            stderr = io.StringIO()
            with patch("clm.cli.cleanup_dest") as cleanup_dest, \
                 patch("clm.cli.reset_source") as reset_source, \
                 patch("clm.cli.start_monitor") as start_monitor, \
                 patch("clm.cli.start_load") as start_load, \
                 patch("clm.cli.run_migration") as run_migration, \
                 redirect_stderr(stderr):
                rc = cli.run_cli(
                    cfg,
                    method=method,
                    repeats=1,
                    load_flags=["cpu"],
                    no_monitor=False,
                    no_migrate=False,
                    no_cleanup=False,
                    auto_analyse=False,
                    env_path="config/env.yaml",
                    cli_argv=["run", "--method", method, "--load", "cpu"],
                )

        self.assertNotEqual(rc, 0)
        cleanup_dest.assert_not_called()
        reset_source.assert_not_called()
        start_monitor.assert_not_called()
        start_load.assert_not_called()
        run_migration.assert_not_called()
        return stderr.getvalue()

    def test_run_cli_blocks_docker_and_containerd_before_baseline_or_monitoring(self):
        for runtime in ("docker", "containerd"):
            with self.subTest(runtime=runtime):
                cfg = deepcopy(cli.DEFAULTS)
                cfg["runtime"] = {"type": runtime}

                err = self._run_cli_expect_capability_gate(cfg)

                self.assertIn("capability gate failed", err)
                self.assertIn(f"Runtime '{runtime}' migration is not implemented", err)

    def test_run_cli_blocks_unknown_runtime_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["runtime"] = {"type": "podman"}

        err = self._run_cli_expect_capability_gate(cfg)

        self.assertIn("Unsupported runtime backend: podman", err)

    def test_run_cli_blocks_rootless_runc_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["runtime"] = {"type": "runc", "rootless": True}

        err = self._run_cli_expect_capability_gate(cfg)

        self.assertIn("Rootless runtime migration is not supported", err)

    def test_run_cli_blocks_unknown_strategy_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)

        err = self._run_cli_expect_capability_gate(cfg, method="teleport")

        self.assertIn("Unknown migration strategy: teleport", err)

    def test_run_cli_blocks_not_implemented_strategy_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)

        err = self._run_cli_expect_capability_gate(cfg, method="stop-and-copy")

        self.assertIn("Migration strategy 'stop-and-copy' is not implemented", err)

    def test_run_cli_blocks_unsupported_criu_custom_build_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["criu"] = {"custom_build": "criu-clm-tcp"}

        err = self._run_cli_expect_capability_gate(cfg)

        self.assertIn("Configured CRIU custom_build 'criu-clm-tcp' is not supported", err)

    def test_run_cli_blocks_command_shell_string_hook_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {
            "mode": "command",
            "hooks": {
                "switch": "lbctl activate dest",
            },
        }

        err = self._run_cli_expect_capability_gate(cfg)

        self.assertIn("traffic hook switch is a shell string", err)
        self.assertIn("allow_shell", err)

    def test_run_cli_blocks_external_legacy_vip_load_before_side_effects(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {"mode": "external"}

        with tempfile.TemporaryDirectory() as tmp:
            runs_root = Path(tmp) / "runs"
            logs_root = Path(tmp) / "logs"
            cfg["paths"]["runs_root"] = str(runs_root)
            cfg["paths"]["logs_root"] = str(logs_root)
            stderr = io.StringIO()
            with patch("clm.cli.cleanup_dest") as cleanup_dest, \
                 patch("clm.cli.reset_source") as reset_source, \
                 patch("clm.cli.start_monitor") as start_monitor, \
                 patch("clm.cli.start_load") as start_load, \
                 patch("clm.cli.run_migration") as run_migration, \
                 redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    cli.run_cli(
                        cfg,
                        method="precopy",
                        repeats=1,
                        load_flags=["wrk1"],
                        no_monitor=False,
                        no_migrate=False,
                        no_cleanup=False,
                        auto_analyse=False,
                        env_path="config/env.yaml",
                        cli_argv=["run", "--method", "precopy", "--load", "wrk1"],
                    )

            self.assertEqual(ctx.exception.code, 1)
            self.assertFalse(runs_root.exists())
            self.assertFalse(logs_root.exists())
        self.assertIn("traffic.mode=external", stderr.getvalue())
        cleanup_dest.assert_not_called()
        reset_source.assert_not_called()
        start_monitor.assert_not_called()
        start_load.assert_not_called()
        run_migration.assert_not_called()

    def test_run_remote_cli_adapter_still_delegates_to_shexecutor_run(self):
        expected = SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with patch("clm.cli.SshExecutor") as ssh_executor:
            ssh_executor.return_value.run.return_value = expected

            result = cli.run_remote(
                "remote1",
                "echo token=abc123",
                check=True,
                capture=True,
                stdout="out",
                stderr="err",
                text=False,
            )

        self.assertIs(result, expected)
        ssh_executor.assert_called_once_with("remote1")
        ssh_executor.return_value.run.assert_called_once_with(
            "echo token=abc123",
            check=True,
            capture=True,
            stdout="out",
            stderr="err",
            text=False,
        )

    def test_run_remote_streamed_cli_adapter_delegates_to_shexecutor_streaming(self):
        expected = SimpleNamespace(returncode=0, stdout="streamed")

        with patch("clm.cli.SshExecutor") as ssh_executor:
            ssh_executor.return_value.run_streamed.return_value = expected

            result = cli._run_remote_streamed("remote1", "printf hi", check=True, tag="baseline:dest")

        self.assertIs(result, expected)
        ssh_executor.assert_called_once_with("remote1")
        ssh_executor.return_value.run_streamed.assert_called_once_with(
            "printf hi",
            check=True,
            on_output=ANY,
        )

    def test_external_run_baseline_does_not_emit_vip_ip_conntrack_or_arping(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {"mode": "external"}

        captured = []

        def fake_run_remote_streamed(host, script, **kwargs):
            captured.append((host, script, kwargs))
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")

            with patch("clm.cli._run_remote_streamed", side_effect=fake_run_remote_streamed), \
                 patch("clm.cli.collect_clock_offsets", return_value={}), \
                 patch("clm.cli.time.sleep", return_value=None), \
                 patch("clm.cli.create_legacy_run_link", return_value=None), \
                 patch("clm.cli.cleanup_run_checkpoint_artifacts", side_effect=AssertionError("cleanup should be skipped")):
                rc = cli.run_cli(
                    cfg,
                    method="precopy",
                    repeats=1,
                    load_flags=None,
                    no_monitor=True,
                    no_migrate=True,
                    no_cleanup=True,
                    auto_analyse=False,
                    env_path="config/env.yaml",
                    cli_argv=["run", "--method", "precopy", "--no-monitor", "--no-migrate"],
                )

        self.assertEqual(rc, 0)
        self.assertEqual([item[0] for item in captured], ["benke2", "benke1"])
        combined = "\n".join(script for _, script, _ in captured)
        self.assertIn("sudo runc --root=/run/runc delete -f \"$NAME\"", combined)
        self.assertNotIn("ip addr add", combined)
        self.assertNotIn("ip addr del", combined)
        self.assertNotIn("conntrack -D", combined)
        self.assertNotIn("arping", combined)
        self.assertNotIn("export VIP_ADDR", combined)

    def test_external_monitor_cmd_omits_vip_targets_and_uses_generic_burst_events(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {"mode": "external"}
        cfg["monitor"]["burst_window_ms"] = 100

        cmd = cli.monitor_cmd(cfg, "run-external", "/tmp/mon", events_log="/tmp/events.ndjson")
        joined = " ".join(cmd)

        self.assertIn("src=http://192.168.13.10:8080/health", joined)
        self.assertIn("dst=http://192.168.13.15:8080/health", joined)
        self.assertNotIn("vip=http://192.168.13.50:8080/health", joined)
        self.assertNotIn("vip=192.168.13.50:8080", joined)
        self.assertIn("traffic_switch_start", cmd)
        self.assertIn("traffic_switch_done", cmd)
        self.assertNotIn("vip_cutover_start", cmd)

    def test_run_cli_without_load_does_not_start_synthetic_load(self):
        cfg = deepcopy(cli.DEFAULTS)

        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")

            with patch("clm.cli.cleanup_dest"), \
                 patch("clm.cli.reset_source"), \
                 patch("clm.cli.collect_clock_offsets", return_value={}), \
                 patch("clm.cli.start_monitor", return_value=(None, None)) as start_monitor, \
                 patch("clm.cli.start_load") as start_load, \
                 patch("clm.cli.analyze_run", return_value=0), \
                 patch("clm.cli.time.sleep", return_value=None), \
                 patch("clm.cli.create_legacy_run_link", return_value=None), \
                 patch("clm.cli.cleanup_run_checkpoint_artifacts", side_effect=AssertionError("cleanup should be skipped")):
                rc = cli.run_cli(
                    cfg,
                    method="precopy",
                    repeats=1,
                    load_flags=None,
                    no_monitor=False,
                    no_migrate=True,
                    no_cleanup=True,
                    auto_analyse=False,
                    env_path="config/env.yaml",
                    cli_argv=["run", "--method", "precopy", "--no-migrate"],
                )

        self.assertEqual(rc, 0)
        start_load.assert_not_called()
        self.assertEqual(start_monitor.call_args.kwargs["load_modes"], [])

    def test_run_cli_with_legacy_load_starts_synthetic_load(self):
        cfg = deepcopy(cli.DEFAULTS)

        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")

            with patch("clm.cli.cleanup_dest"), \
                 patch("clm.cli.reset_source"), \
                 patch("clm.cli.collect_clock_offsets", return_value={}), \
                 patch("clm.cli.start_monitor", return_value=(None, None)) as start_monitor, \
                 patch("clm.cli.start_load", return_value=[]) as start_load, \
                 patch("clm.cli.analyze_run", return_value=0), \
                 patch("clm.cli.time.sleep", return_value=None), \
                 patch("clm.cli.create_legacy_run_link", return_value=None), \
                 patch("clm.cli.cleanup_run_checkpoint_artifacts", side_effect=AssertionError("cleanup should be skipped")):
                rc = cli.run_cli(
                    cfg,
                    method="precopy",
                    repeats=1,
                    load_flags=["cpu"],
                    no_monitor=False,
                    no_migrate=True,
                    no_cleanup=True,
                    auto_analyse=False,
                    env_path="config/env.yaml",
                    cli_argv=["run", "--method", "precopy", "--load", "cpu", "--no-migrate"],
                )

        self.assertEqual(rc, 0)
        start_load.assert_called_once()
        self.assertEqual(start_load.call_args.args[2], ["cpu"])
        self.assertEqual(start_monitor.call_args.kwargs["load_modes"], ["cpu"])

    def test_vip_run_baseline_keeps_legacy_vip_cleanup(self):
        cfg = deepcopy(cli.DEFAULTS)

        captured = []

        def fake_run_remote_streamed(host, script, **kwargs):
            captured.append((host, script, kwargs))
            return SimpleNamespace(returncode=0)

        with patch("clm.cli._run_remote_streamed", side_effect=fake_run_remote_streamed):
            cli.cleanup_dest(cfg)
            cli.reset_source(cfg)

        combined = "\n".join(script for _, script, _ in captured)
        self.assertIn("export VIP_ADDR=192.168.13.50", combined)
        self.assertIn("sudo ip addr del \"${VIP_ADDR}${VIP_CIDR}\" dev \"$VIP_IF_DST\"", combined)
        self.assertIn("sudo conntrack -D -d \"$VIP_ADDR\"", combined)
        self.assertIn("sudo ip addr add \"${VIP_ADDR}${VIP_CIDR}\" dev \"$VIP_IF_SRC\"", combined)
        self.assertIn("sudo arping -c 3 -A -I \"$VIP_IF_SRC\" \"$VIP_ADDR\"", combined)

    def test_precopy_run_migration_exports_shared_image_mode_by_default(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["hosts"]["dest"]["user"] = "benke2"

        captured = {}

        def fake_run_remote(host, script, **kwargs):
            captured["host"] = host
            captured["script"] = script
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            migrate_log = Path(tmp) / "migrate" / "precopy.log"
            with patch("clm.cli.run_remote", side_effect=fake_run_remote):
                rc = cli.run_migration(
                    cfg,
                    method="precopy",
                    run_id="20260325_120000",
                    events_log="/mnt/criu/logs/mon-20260325_120000-events.ndjson",
                    migrate_log=str(migrate_log),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["host"], "benke1")
        self.assertIn("export PRECOPY_IMAGE_MODE=shared", captured["script"])
        self.assertIn("bash \"$REPO/scripts/migrate_precopy.sh\"", captured["script"])

    def test_precopy_run_migration_exports_local_copy_override(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["hosts"]["dest"]["user"] = "benke2"
        cfg["precopy"]["image_mode"] = "local_copy"

        captured = {}

        def fake_run_remote(host, script, **kwargs):
            captured["host"] = host
            captured["script"] = script
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            migrate_log = Path(tmp) / "migrate" / "precopy.log"
            with patch("clm.cli.run_remote", side_effect=fake_run_remote):
                rc = cli.run_migration(
                    cfg,
                    method="precopy",
                    run_id="20260325_120001",
                    events_log="/mnt/criu/logs/mon-20260325_120001-events.ndjson",
                    migrate_log=str(migrate_log),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["host"], "benke1")
        self.assertIn("export PRECOPY_IMAGE_MODE=local_copy", captured["script"])

    def test_postcopy_run_migration_uses_recommended_readiness_fallback_defaults(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["hosts"]["dest"]["user"] = "benke2"
        cfg["postcopy"].pop("readiness_stable_successes", None)
        cfg["postcopy"].pop("readiness_timeout_ms", None)

        captured = {}

        def fake_run_remote(host, script, **kwargs):
            captured["host"] = host
            captured["script"] = script
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            migrate_log = Path(tmp) / "migrate" / "postcopy.log"
            with patch("clm.cli.run_remote", side_effect=fake_run_remote):
                rc = cli.run_migration(
                    cfg,
                    method="postcopy",
                    run_id="20260325_120002",
                    events_log="/mnt/criu/logs/mon-20260325_120002-events.ndjson",
                    migrate_log=str(migrate_log),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["host"], "benke1")
        self.assertIn("export POSTCOPY_READINESS_STABLE_SUCCESSES=3", captured["script"])
        self.assertIn("export POSTCOPY_READINESS_TIMEOUT_MS=10000", captured["script"])
        readiness_line = next(
            line for line in captured["script"].splitlines()
            if line.startswith("export POSTCOPY_READINESS_URLS=")
        )
        self.assertEqual(readiness_line, "export POSTCOPY_READINESS_URLS=http://192.168.13.15:8080/health")

    def test_postcopy_run_migration_corrects_invalid_readiness_when_forwarding_enabled(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["hosts"]["dest"]["user"] = "benke2"
        cfg["postcopy"]["src_forwarding_enabled"] = 1
        cfg["postcopy"]["readiness_stable_successes"] = 0
        cfg["postcopy"]["readiness_timeout_ms"] = 0

        captured = {}

        def fake_run_remote(host, script, **kwargs):
            captured["host"] = host
            captured["script"] = script
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            migrate_log = Path(tmp) / "migrate" / "postcopy_guardrail.log"
            with patch("clm.cli.run_remote", side_effect=fake_run_remote):
                rc = cli.run_migration(
                    cfg,
                    method="postcopy",
                    run_id="20260325_120003",
                    events_log="/mnt/criu/logs/mon-20260325_120003-events.ndjson",
                    migrate_log=str(migrate_log),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["host"], "benke1")
        self.assertIn("export POSTCOPY_READINESS_STABLE_SUCCESSES=3", captured["script"])
        self.assertIn("export POSTCOPY_READINESS_TIMEOUT_MS=10000", captured["script"])

    def test_analyze_run_includes_precopy_image_mode_in_summary(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["precopy"]["image_mode"] = "local_copy"
        cfg["precopy"]["pre_dump_rounds"] = 1
        cfg["precopy"]["tcp_established"] = 0

        analyze_stdout = json.dumps({"status": "ok", "vip_http_downtime_ms": 123.0})

        def fake_run_local(cmd, **kwargs):
            self.assertIn("--analyze", cmd)
            return SimpleNamespace(returncode=0, stdout=analyze_stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "0001"
            (run_dir / "monitor").mkdir(parents=True, exist_ok=True)
            events_log = str(run_dir / "events" / "events.ndjson")
            base_out = str(run_dir / "monitor" / "mon")

            with patch("clm.cli.run_local", side_effect=fake_run_local):
                rc = cli.analyze_run(cfg, base_out, events_log, str(run_dir))

            self.assertEqual(rc, 0)
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["migration_params"]["precopy_image_mode"], "local_copy")
            self.assertEqual(summary["migration_params"]["precopy_pre_dump_rounds"], 1)
            self.assertEqual(summary["migration_params"]["precopy_tcp_established"], 0)
            self.assertEqual(summary["vip_http_downtime_ms"], 123.0)

    def test_analyze_run_writes_core_status_and_downtime_without_vip_metrics(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["traffic"] = {"mode": "external"}

        analyze_stdout = json.dumps({"http_downtime_ms": 44.0, "l4_downtime_ms": 55.0})

        def fake_run_local(cmd, **kwargs):
            self.assertIn("--analyze", cmd)
            return SimpleNamespace(returncode=0, stdout=analyze_stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "0003"
            (run_dir / "monitor").mkdir(parents=True, exist_ok=True)
            events_log = str(run_dir / "events" / "events.ndjson")
            base_out = str(run_dir / "monitor" / "mon")

            with patch("clm.cli.run_local", side_effect=fake_run_local):
                rc = cli.analyze_run(cfg, base_out, events_log, str(run_dir))

            self.assertEqual(rc, 0)
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["core_status"], "ok")
            self.assertEqual(summary["core_downtime_ms"], 44.0)
            self.assertEqual(summary["core_summary"]["downtime_ms"], 44.0)
            self.assertEqual(summary["migration_params"]["traffic_mode"], "external")
            self.assertNotIn("vip_http_downtime_ms", summary)

    def test_analyze_run_uses_recommended_postcopy_readiness_defaults_in_summary(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["postcopy"].pop("readiness_stable_successes", None)
        cfg["postcopy"].pop("readiness_timeout_ms", None)

        analyze_stdout = json.dumps({"status": "ok", "vip_http_downtime_ms": 111.0})

        def fake_run_local(cmd, **kwargs):
            self.assertIn("--analyze", cmd)
            return SimpleNamespace(returncode=0, stdout=analyze_stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "0002"
            (run_dir / "monitor").mkdir(parents=True, exist_ok=True)
            events_log = str(run_dir / "events" / "events.ndjson")
            base_out = str(run_dir / "monitor" / "mon")

            with patch("clm.cli.run_local", side_effect=fake_run_local):
                rc = cli.analyze_run(cfg, base_out, events_log, str(run_dir))

            self.assertEqual(rc, 0)
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["migration_params"]["postcopy_readiness_stable_successes"], 3)
            self.assertEqual(summary["migration_params"]["postcopy_readiness_timeout_ms"], 10000)

    def test_cleanup_skipped_checkpoint_artifacts_describes_paths(self):
        cfg = deepcopy(cli.DEFAULTS)
        info = cli.cleanup_skipped_checkpoint_artifacts(
            cfg,
            method="precopy",
            run_id="20260325_190000",
            reason="cli_no_cleanup",
        )
        self.assertTrue(info["skipped"])
        self.assertEqual(info["reason"], "cli_no_cleanup")
        self.assertEqual(info["cp_name"], "pc-20260325_190000")
        self.assertEqual(info["shared"]["path"], "/mnt/criu/runc/testweb/pc-20260325_190000")
        self.assertEqual(info["local"]["path"], "/var/lib/criu-local/runc/testweb/pc-20260325_190000")
        self.assertFalse(info["shared"]["attempted"])
        self.assertFalse(info["local"]["attempted"])

    def test_run_cli_no_cleanup_skips_checkpoint_artifact_cleanup(self):
        cfg = deepcopy(cli.DEFAULTS)
        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")

            with patch("clm.cli.cleanup_dest"), \
                 patch("clm.cli.reset_source"), \
                 patch("clm.cli.collect_clock_offsets", return_value={}), \
                 patch("clm.cli.time.sleep", return_value=None), \
                 patch("clm.cli.create_legacy_run_link", return_value=None), \
                 patch("clm.cli.cleanup_run_checkpoint_artifacts", side_effect=AssertionError("cleanup should be skipped")):
                rc = cli.run_cli(
                    cfg,
                    method="precopy",
                    repeats=1,
                    load_flags=None,
                    no_monitor=True,
                    no_migrate=True,
                    no_cleanup=True,
                    auto_analyse=False,
                    env_path="config/env.yaml",
                    cli_argv=["run", "--method", "precopy", "--no-cleanup", "--no-monitor", "--no-migrate"],
                )

            self.assertEqual(rc, 0)
            cleanup_files = list((Path(tmp) / "runs").glob("batches/*/runs/*/meta/cleanup.json"))
            self.assertEqual(len(cleanup_files), 1)
            cleanup_info = json.loads(cleanup_files[0].read_text(encoding="utf-8"))
            self.assertTrue(cleanup_info["skipped"])
            self.assertEqual(cleanup_info["reason"], "cli_no_cleanup")

    def test_run_cli_postcopy_corrects_readiness_gate_in_config_snapshot(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["postcopy"]["src_forwarding_enabled"] = 1
        cfg["postcopy"]["readiness_stable_successes"] = 0
        cfg["postcopy"]["readiness_timeout_ms"] = 0

        with tempfile.TemporaryDirectory() as tmp:
            cfg["paths"]["runs_root"] = str(Path(tmp) / "runs")
            cfg["paths"]["logs_root"] = str(Path(tmp) / "logs")

            with patch("clm.cli.cleanup_dest"), \
                 patch("clm.cli.reset_source"), \
                 patch("clm.cli.collect_clock_offsets", return_value={}), \
                 patch("clm.cli.time.sleep", return_value=None), \
                 patch("clm.cli.create_legacy_run_link", return_value=None), \
                 patch("clm.cli.cleanup_run_checkpoint_artifacts", side_effect=AssertionError("cleanup should be skipped")):
                rc = cli.run_cli(
                    cfg,
                    method="postcopy",
                    repeats=1,
                    load_flags=None,
                    no_monitor=True,
                    no_migrate=True,
                    no_cleanup=True,
                    auto_analyse=False,
                    env_path="config/env.yaml",
                    cli_argv=["run", "--method", "postcopy", "--no-cleanup", "--no-monitor", "--no-migrate"],
                )

            self.assertEqual(rc, 0)
            snapshots = list((Path(tmp) / "runs").glob("batches/*/runs/*/meta/config_snapshot.yaml"))
            self.assertEqual(len(snapshots), 1)
            cfg_snapshot = yaml.safe_load(snapshots[0].read_text(encoding="utf-8"))
            self.assertEqual(cfg_snapshot["postcopy"]["readiness_stable_successes"], 3)
            self.assertEqual(cfg_snapshot["postcopy"]["readiness_timeout_ms"], 10000)

    def test_reset_source_exports_configured_gunicorn_capacity(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["container"]["gunicorn"] = {"workers": 2, "threads": 8}

        captured = {}

        def fake_run_remote_streamed(host, script, **kwargs):
            captured["host"] = host
            captured["script"] = script
            return SimpleNamespace(returncode=0)

        with patch("clm.cli._run_remote_streamed", side_effect=fake_run_remote_streamed):
            cli.reset_source(cfg)

        self.assertEqual(captured["host"], "benke1")
        self.assertIn("export GUNICORN_WORKERS=2", captured["script"])
        self.assertIn("export GUNICORN_THREADS=8", captured["script"])
        self.assertIn("bash \"$REPO/scripts/patch_runc_bundle_for_criu.sh\" \"$BUNDLE\"", captured["script"])


if __name__ == "__main__":
    unittest.main()
