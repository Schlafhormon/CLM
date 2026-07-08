#!/usr/bin/env python3

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import clm.cli as cli
from clm.core.models import RuntimeRef
from clm.runtimes import (
    ContainerdBackend,
    DockerBackend,
    MigrationNotImplementedError,
    RuncBackend,
    select_backend,
)


class RuntimeBackendSelectionTests(unittest.TestCase):
    def test_default_backend_is_runc_for_legacy_config(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg.pop("runtime", None)
        cfg["container"].pop("runtime", None)

        backend = select_backend(cfg)

        self.assertIsInstance(backend, RuncBackend)
        self.assertEqual(backend.runtime.type, "runc")

    def test_backend_selection_uses_config_runtime(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["runtime"] = {"type": "docker", "socket_path": "/run/docker.sock"}

        backend = select_backend(cfg)

        self.assertIsInstance(backend, DockerBackend)
        self.assertEqual(backend.runtime.socket_path, "/run/docker.sock")

    def test_backend_selection_uses_container_runtime_fallback(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["container"]["runtime"] = "containerd"

        backend = select_backend(cfg)

        self.assertIsInstance(backend, ContainerdBackend)

    def test_backend_selection_accepts_runtime_ref(self):
        backend = select_backend(RuntimeRef(type="containerd", socket_path="/run/containerd/containerd.sock"))

        self.assertIsInstance(backend, ContainerdBackend)
        self.assertEqual(backend.runtime.socket_path, "/run/containerd/containerd.sock")


class RuntimeBackendMigrationTests(unittest.TestCase):
    def test_runc_backend_adapts_legacy_precopy_script(self):
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
                result = RuncBackend().migrate(
                    cfg,
                    method="precopy",
                    run_id="20260325_120000",
                    events_log="/mnt/criu/logs/mon-20260325_120000-events.ndjson",
                    migrate_log=str(migrate_log),
                )

        self.assertTrue(result.ok)
        self.assertEqual(result.artifacts["returncode"], 0)
        self.assertEqual(captured["host"], "benke1")
        self.assertIn("export MODE=runc", captured["script"])
        self.assertIn("export TRAFFIC_MODE=vip", captured["script"])
        self.assertIn("bash \"$REPO/scripts/migrate_precopy_vip_cutover.sh\"", captured["script"])

    def test_runc_backend_exports_command_traffic_hooks(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["traffic"] = {
            "mode": "command",
            "hooks": {
                "prepare": ["lbctl", "drain", "source"],
                "switch": ["lbctl", "activate", "dest"],
                "verify": ["curl", "-fsS", "http://service/health"],
            },
        }

        script = RuncBackend().build_legacy_migration_script(
            cfg,
            method="precopy",
            run_id="run-command",
            events_log="/tmp/events.ndjson",
        )

        self.assertIn("export TRAFFIC_MODE=command", script)
        self.assertIn("export TRAFFIC_PREPARE_CMD='lbctl drain source'", script)
        self.assertIn("export TRAFFIC_SWITCH_CMD='lbctl activate dest'", script)
        self.assertIn("export TRAFFIC_VERIFY_CMD='curl -fsS http://service/health'", script)

    def test_docker_migration_fails_fast(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["runtime"] = {"type": "docker"}

        backend = select_backend(cfg)

        with self.assertRaises(MigrationNotImplementedError):
            backend.migrate(
                cfg,
                method="precopy",
                run_id="run1",
                events_log="/tmp/events.ndjson",
                migrate_log="/tmp/migrate.log",
            )

    def test_containerd_migration_fails_fast(self):
        backend = select_backend(RuntimeRef(type="containerd"))

        with self.assertRaises(MigrationNotImplementedError):
            backend.migrate(
                deepcopy(cli.DEFAULTS),
                method="postcopy",
                run_id="run2",
                events_log="/tmp/events.ndjson",
                migrate_log="/tmp/migrate.log",
            )

    def test_placeholder_backends_have_preflight_and_inspect_skeletons(self):
        docker = DockerBackend(RuntimeRef(type="docker", socket_path="/run/docker.sock"))
        containerd = ContainerdBackend(RuntimeRef(type="containerd", socket_path="/run/containerd/containerd.sock"))

        self.assertTrue(docker.preflight().ok)
        self.assertEqual(docker.inspect("web").status, "placeholder")
        self.assertFalse(docker.inspect("web").details["migration_supported"])
        self.assertTrue(containerd.preflight().ok)
        self.assertEqual(containerd.inspect("web").status, "placeholder")
        self.assertFalse(containerd.inspect("web").details["migration_supported"])


if __name__ == "__main__":
    unittest.main()
