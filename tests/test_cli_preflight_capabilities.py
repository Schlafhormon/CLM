#!/usr/bin/env python3

import io
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import clm.cli as cli


class CliPreflightCapabilityGateTests(unittest.TestCase):
    def _preflight_expect_gate_block(self, cfg):
        stdout = io.StringIO()
        with patch("clm.cli.run_remote", side_effect=AssertionError("remote call should not happen")) as run_remote, \
             patch("clm.cli.run_shell_local", side_effect=AssertionError("local shell check should not happen")) as run_shell_local, \
             patch("clm.cli.ensure_dir", side_effect=AssertionError("NFS write setup should not happen")) as ensure_dir, \
             redirect_stdout(stdout):
            rc = cli.preflight(cfg)

        self.assertEqual(rc, 1)
        run_remote.assert_not_called()
        run_shell_local.assert_not_called()
        ensure_dir.assert_not_called()
        out = stdout.getvalue()
        self.assertIn("Capability gate:", out)
        self.assertIn("Preflight FAILED", out)
        self.assertNotIn("monitor: repo vorhanden", out)
        self.assertNotIn("source: ssh ok", out)
        return out

    def test_preflight_blocks_docker_and_containerd_before_remote_checks(self):
        for runtime in ("docker", "containerd"):
            with self.subTest(runtime=runtime):
                cfg = deepcopy(cli.DEFAULTS)
                cfg["runtime"] = {"type": runtime}

                out = self._preflight_expect_gate_block(cfg)

                self.assertIn(f"Runtime '{runtime}' migration is not implemented", out)

    def test_preflight_blocks_rootless_runc_before_remote_checks(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["runtime"] = {"type": "runc", "rootless": True}

        out = self._preflight_expect_gate_block(cfg)

        self.assertIn("Rootless runtime migration is not supported", out)

    def test_preflight_blocks_custom_criu_binary_and_build_before_remote_checks(self):
        cases = (
            ({"binary": "/opt/criu-custom/bin/criu-custom"}, "Configured CRIU binary"),
            ({"custom_build": "criu-clm-tcp"}, "Configured CRIU custom_build 'criu-clm-tcp'"),
        )
        for criu, expected in cases:
            with self.subTest(criu=criu):
                cfg = deepcopy(cli.DEFAULTS)
                cfg["criu"] = criu

                out = self._preflight_expect_gate_block(cfg)

                self.assertIn(expected, out)

    def test_preflight_blocks_unsafe_command_traffic_hook_before_remote_checks(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {
            "mode": "command",
            "hooks": {
                "switch": "lbctl activate dest",
            },
        }

        out = self._preflight_expect_gate_block(cfg)

        self.assertIn("traffic hook switch is a shell string", out)
        self.assertIn("allow_shell", out)

    def test_preflight_blocks_unsupported_traffic_mode_before_remote_checks(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["traffic"] = {"mode": "magic-lb"}

        out = self._preflight_expect_gate_block(cfg)

        self.assertIn("Unsupported traffic backend: magic-lb", out)

    def test_preflight_blocks_unsupported_storage_before_remote_checks(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["storage"] = {"mode": "stream"}

        out = self._preflight_expect_gate_block(cfg)

        self.assertIn("Unsupported storage backend: stream", out)


if __name__ == "__main__":
    unittest.main()
