#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import yaml

import clm.cli as cli
from clm.core import config as core_config
from clm.core.models import (
    ContainerRef,
    HostRef,
    MigrationRequest,
    MigrationResult,
    PreflightResult,
    ProbeSpec,
    RuntimeRef,
)


class CoreModelsTests(unittest.TestCase):
    def test_probe_and_result_models_normalize_sequences(self):
        probe = ProbeSpec(name="health", type="command", command=["curl", "-f", "http://app/health"])
        self.assertEqual(probe.command, ("curl", "-f", "http://app/health"))

        ok_result = MigrationResult(migration_id="m1", status="ok", warnings=["slow cutover"])
        self.assertTrue(ok_result.ok)
        self.assertEqual(ok_result.warnings, ("slow cutover",))

    def test_preflight_result_reports_blockers(self):
        clean = PreflightResult(checks=({"name": "criu", "ok": True},))
        blocked = PreflightResult(checks=({"name": "ssh", "ok": True},), blockers=["dest unreachable"])

        self.assertTrue(clean.ok)
        self.assertFalse(blocked.ok)

    def test_migration_request_requires_container_or_group(self):
        source = HostRef(role="source", host="src")
        dest = HostRef(role="dest", host="dst")
        runtime = RuntimeRef(type="runc")
        container = ContainerRef(identifier="app", runtime=runtime)

        request = MigrationRequest(source=source, destination=dest, container=container, runtime=runtime)
        self.assertEqual(request.container.identifier, "app")

        with self.assertRaises(ValueError):
            MigrationRequest(source=source, destination=dest)


class CoreConfigTests(unittest.TestCase):
    def test_load_legacy_env_matches_cli_loader_for_example_config(self):
        path = Path("config/env.example.yaml")
        core_cfg = core_config.load_legacy_env(path)
        cli_cfg = cli.load_env(str(path))

        self.assertEqual(core_cfg["hosts"], cli_cfg["hosts"])
        self.assertEqual(core_cfg["paths"], cli_cfg["paths"])
        self.assertEqual(core_cfg["vip"], cli_cfg["vip"])

    def test_legacy_env_to_migration_request_derives_core_models(self):
        cfg = core_config.load_legacy_env("config/env.example.yaml")
        request = core_config.legacy_env_to_migration_request(cfg, method="precopy")

        self.assertEqual(request.source.role, "source")
        self.assertEqual(request.source.host, "benke1")
        self.assertEqual(request.destination.host, "benke2")
        self.assertEqual(request.runtime.type, "runc")
        self.assertEqual(request.strategy, "pre-copy")
        self.assertEqual(request.container.identifier, "testweb")
        self.assertEqual(request.container.bundle_path, "/mnt/criu/runc-bundle")
        self.assertEqual(request.storage.mode, "shared")
        self.assertEqual(request.storage.share_root, "/mnt/criu")
        self.assertEqual(request.traffic.mode, "vip")
        self.assertEqual(request.traffic.vip_addr, "192.168.13.50")
        self.assertEqual(request.traffic.port, 8080)
        self.assertTrue(any(probe.name == "postcopy-readiness-1" for probe in request.probes))

    def test_load_migration_request_accepts_string_hosts_and_explicit_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "hosts": {
                            "monitor": "local",
                            "source": "src.example",
                            "dest": {"host": "dst.example", "ip": "10.0.0.2", "user": "clm"},
                        },
                        "runtime": {"type": "docker", "socket_path": "/run/docker.sock", "rootless": True},
                        "container": {"name": "web", "image": "example/web:latest"},
                        "traffic": {"mode": "external"},
                        "probes": [
                            {
                                "name": "tcp-ready",
                                "type": "tcp",
                                "host": "10.0.0.2",
                                "port": 8080,
                                "required": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            request = core_config.load_migration_request(path, method="postcopy")

        self.assertTrue(request.monitor.local)
        self.assertEqual(request.source.host, "src.example")
        self.assertEqual(request.destination.user, "clm")
        self.assertEqual(request.runtime.type, "docker")
        self.assertTrue(request.runtime.rootless)
        self.assertEqual(request.runtime.privilege_mode, "rootless")
        self.assertEqual(request.strategy, "post-copy")
        self.assertEqual(request.traffic.mode, "external")
        self.assertEqual(request.probes[0].name, "tcp-ready")
        self.assertTrue(request.probes[0].required)


if __name__ == "__main__":
    unittest.main()
