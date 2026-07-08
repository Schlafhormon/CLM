#!/usr/bin/env python3

import subprocess
import unittest
from copy import deepcopy

import clm.cli as cli
from clm.core.models import TrafficPlan
from clm.host import LocalExecutor
from clm.migration.traffic import (
    CommandTrafficBackend,
    ExternalTrafficBackend,
    TrafficConfigError,
    VipTrafficBackend,
    select_traffic_backend,
)


class TrafficBackendSelectionTests(unittest.TestCase):
    def test_external_backend_is_noop_without_verify_hook(self):
        backend = select_traffic_backend({"traffic": {"mode": "external"}})

        self.assertIsInstance(backend, ExternalTrafficBackend)
        self.assertTrue(backend.preflight().ok)
        self.assertTrue(backend.prepare().skipped)
        self.assertTrue(backend.switch().skipped)
        self.assertTrue(backend.verify().skipped)
        self.assertEqual(backend.script_env(), {"TRAFFIC_MODE": "external"})

    def test_legacy_vip_config_selects_vip_backend(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg.pop("traffic", None)

        backend = select_traffic_backend(cfg)

        self.assertIsInstance(backend, VipTrafficBackend)
        self.assertTrue(backend.preflight().ok)
        env = backend.script_env(cfg)
        self.assertEqual(env["TRAFFIC_MODE"], "vip")
        self.assertEqual(env["VIP_ADDR"], "192.168.13.50")
        self.assertEqual(env["VIP_PORT"], 8080)
        self.assertEqual(env["VIP_IF_SRC"], "enp1s0")

    def test_explicit_traffic_vip_keeps_legacy_vip_values(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {"mode": "vip"}

        backend = select_traffic_backend(cfg)

        self.assertIsInstance(backend, VipTrafficBackend)
        self.assertEqual(backend.plan.vip_addr, cfg["vip"]["addr"])
        self.assertEqual(backend.plan.interfaces["dest"], cfg["vip"]["if_dest"])


class CommandTrafficBackendTests(unittest.TestCase):
    def test_command_hooks_use_argv_lists_and_report_results(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

        backend = CommandTrafficBackend(
            TrafficPlan(
                mode="command",
                hooks={
                    "prepare": ["lbctl", "drain", "source"],
                    "switch": ["lbctl", "activate", "dest"],
                    "verify": ["curl", "-fsS", "http://service/health"],
                },
            ),
            executor=LocalExecutor(runner=fake_runner),
        )

        self.assertTrue(backend.preflight().ok)
        self.assertTrue(backend.prepare().ok)
        self.assertTrue(backend.switch().ok)
        self.assertTrue(backend.verify().ok)
        self.assertEqual(calls[0][0], ["lbctl", "drain", "source"])
        self.assertEqual(calls[0][1]["stdout"], subprocess.PIPE)
        self.assertEqual(calls[0][1]["stderr"], subprocess.PIPE)
        self.assertEqual(
            backend.script_env(),
            {
                "TRAFFIC_MODE": "command",
                "TRAFFIC_PREPARE_CMD": "lbctl drain source",
                "TRAFFIC_SWITCH_CMD": "lbctl activate dest",
                "TRAFFIC_VERIFY_CMD": "curl -fsS http://service/health",
            },
        )

    def test_shell_string_hooks_require_explicit_allow_shell(self):
        backend = CommandTrafficBackend(
            TrafficPlan(mode="command", hooks={"switch": "lbctl activate dest"})
        )

        result = backend.preflight()

        self.assertFalse(result.ok)
        self.assertIn("allow_shell", result.blockers[0])
        with self.assertRaises(TrafficConfigError):
            backend.switch()

    def test_shell_string_hook_can_be_enabled_explicitly(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        backend = CommandTrafficBackend(
            TrafficPlan(
                mode="command",
                hooks={"switch": {"command": "lbctl activate dest", "allow_shell": True}},
            ),
            executor=LocalExecutor(runner=fake_runner),
        )

        self.assertTrue(backend.preflight().ok)
        self.assertTrue(backend.switch().ok)
        self.assertEqual(calls[0], ["bash", "-lc", "lbctl activate dest"])


if __name__ == "__main__":
    unittest.main()
