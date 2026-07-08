#!/usr/bin/env python3


import copy
import unittest
from unittest import mock

import clm.cli as cli


class CliLoadProfilesTests(unittest.TestCase):
    def test_parse_load_modes_defaults_to_no_synthetic_load(self):
        self.assertEqual(cli.parse_load_modes(None), [])
        self.assertEqual(cli.parse_load_modes(["idle"]), [])

    def test_legacy_synthetic_load_profile_list_is_explicit(self):
        self.assertEqual(
            cli.LEGACY_SYNTHETIC_LOAD_PROFILES,
            ("cpu", "wrk", "wrk1", "wrk2", "wrk3", "download", "upload", "stream"),
        )

    def test_parse_load_modes_accepts_named_wrk_profiles(self):
        self.assertEqual(cli.parse_load_modes(["wrk1"]), ["wrk1"])
        self.assertEqual(cli.parse_load_modes(["cpu,wrk2,download,wrk3"]), ["cpu", "wrk2", "download", "wrk3"])

    def test_start_load_wrk_requires_binary(self):
        cfg = copy.deepcopy(cli.DEFAULTS)
        cfg["paths"]["logs_root"] = "/tmp/clm-test-logs"
        with mock.patch("clm.cli.shutil.which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                cli.start_load(cfg, "run-1", ["wrk1"])
        self.assertEqual(ctx.exception.code, 1)

    def test_start_load_builds_wrk_loop(self):
        cfg = copy.deepcopy(cli.DEFAULTS)
        cfg["paths"]["logs_root"] = "/tmp/clm-test-logs"
        cfg["load"]["wrk2"].update(
            {
                "target": "vip",
                "parallel": 1,
                "threads": 4,
                "connections": 32,
                "duration_s": 15,
                "timeout_s": 3,
                "path": "/ready",
                "latency": True,
            }
        )

        with mock.patch("clm.cli.shutil.which", return_value="/usr/bin/wrk"):
            with mock.patch("clm.cli._spawn_load_loop", return_value=("proc", "fp", "wrk2-vip-1")) as spawn:
                procs = cli.start_load(cfg, "run-1", ["wrk2"])

        self.assertEqual(procs, [("proc", "fp", "wrk2-vip-1")])
        self.assertEqual(spawn.call_count, 1)
        logs_root, run_id, proc_id, body = spawn.call_args[0]
        self.assertEqual(logs_root, "/tmp/clm-test-logs")
        self.assertEqual(run_id, "run-1")
        self.assertEqual(proc_id, "wrk2-vip-1")
        self.assertIn("wrk", body)
        self.assertIn("-t 4", body)
        self.assertIn("-c 32", body)
        self.assertIn("-d 15s", body)
        self.assertIn("--timeout 3s", body)
        self.assertIn("--latency", body)
        self.assertIn("http://192.168.13.50:8080/ready", body)

    def test_monitor_cmd_without_load_uses_core_targets_only(self):
        cfg = copy.deepcopy(cli.DEFAULTS)

        cmd = cli.monitor_cmd(cfg, "run-1", "/tmp/mon", load_modes=None)
        joined = " ".join(cmd)

        self.assertIn("src=http://192.168.13.10:8080/health", joined)
        self.assertIn("dst=http://192.168.13.15:8080/health", joined)
        self.assertIn("vip=http://192.168.13.50:8080/health", joined)
        self.assertNotIn("--info-target", cmd)
        self.assertNotIn("--counter-target", cmd)
        self.assertNotIn("--stream-target", cmd)
        self.assertNotIn("--download-target", cmd)
        self.assertNotIn("--upload-target", cmd)

    def test_monitor_cmd_with_legacy_load_enables_legacy_targets(self):
        cfg = copy.deepcopy(cli.DEFAULTS)

        cmd = cli.monitor_cmd(cfg, "run-1", "/tmp/mon", load_modes=["download", "stream"])

        self.assertIn("--info-target", cmd)
        self.assertIn("--counter-target", cmd)
        self.assertIn("--stream-target", cmd)
        self.assertIn("--download-target", cmd)

    def test_monitor_cmd_adds_explicit_probe_targets(self):
        cfg = copy.deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {"mode": "external"}
        cfg["probes"] = [
            {
                "name": "service-health",
                "type": "http",
                "target": "service",
                "url": "http://service.example/health",
            },
            {
                "name": "vip-observer",
                "type": "tcp",
                "target": "vip",
                "host": "192.168.13.50",
                "port": 8080,
            },
        ]

        cmd = cli.monitor_cmd(cfg, "run-1", "/tmp/mon", load_modes=None)
        joined = " ".join(cmd)

        self.assertIn("service=http://service.example/health", joined)
        self.assertIn("vip=192.168.13.50:8080", joined)
        self.assertNotIn("vip=http://192.168.13.50:8080/health", joined)


if __name__ == "__main__":
    unittest.main()
