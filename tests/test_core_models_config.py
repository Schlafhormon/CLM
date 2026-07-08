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

    def test_traffic_config_accepts_nested_vip_compatibility_fields(self):
        cfg = core_config.load_legacy_env("config/env.example.yaml")
        cfg["traffic"] = {
            "mode": "vip",
            "vip": {
                "addr": "10.10.10.10",
                "cidr": "/32",
                "port": 9090,
                "if_source": "eth-src",
                "if_dest": "eth-dst",
            },
        }

        traffic = core_config.traffic_from_legacy_env(cfg)

        self.assertEqual(traffic.mode, "vip")
        self.assertEqual(traffic.vip_addr, "10.10.10.10")
        self.assertEqual(traffic.vip_cidr, "/32")
        self.assertEqual(traffic.port, 9090)
        self.assertEqual(traffic.interfaces["source"], "eth-src")
        self.assertEqual(traffic.interfaces["dest"], "eth-dst")

    def test_load_clm_v1_example_derives_core_request(self):
        request = core_config.load_clm_v1_migration_request("config/clm.example.yaml")

        self.assertEqual(request.source.host, "source.example.net")
        self.assertEqual(request.destination.host, "dest.example.net")
        self.assertEqual(request.monitor.host, "local")
        self.assertTrue(request.monitor.local)
        self.assertEqual(request.runtime.type, "runc")
        self.assertEqual(request.runtime.privilege_mode, "rootful")
        self.assertFalse(request.runtime.rootless)
        self.assertEqual(request.container.identifier, "web")
        self.assertEqual(request.container.bundle_path, "/srv/clm/runc-bundles/web")
        self.assertEqual(request.criu.binary, "/usr/sbin/criu")
        self.assertEqual(request.criu.custom_build, "criu-clm-tcp")
        self.assertIn("lazy-pages", request.criu.features)
        self.assertEqual(request.strategy, "stop-and-copy")
        self.assertEqual(request.storage.mode, "shared")
        self.assertEqual(request.storage.share_root, "/mnt/criu")
        self.assertEqual(request.storage.options["destination_root"], "/var/lib/criu-local")
        self.assertEqual(request.storage.cleanup_policy["shared_images_policy"], "success_only")
        self.assertEqual(request.traffic.mode, "external")
        self.assertIn("verify", request.traffic.hooks)
        self.assertEqual([probe.name for probe in request.probes], ["app-health", "app-port", "custom-ready"])
        self.assertTrue(request.probes[0].required)
        self.assertEqual(request.options["output"]["console_summary"], True)

    def test_clm_v1_parser_accepts_container_group_and_command_traffic(self):
        cfg = {
            "version": 1,
            "source": "src.example",
            "destination": {"host": "dst.example", "ip": "10.0.0.2"},
            "runtime": {"type": "containerd", "socket_path": "/run/containerd/containerd.sock", "rootless": True},
            "container_group": {
                "name": "stack",
                "containers": [
                    {"id": "db", "image": "postgres:16"},
                    {"id": "web", "image": "example/web:latest"},
                ],
                "dependencies": {"web": ["db"]},
            },
            "strategy": {"mode": "pre-copy"},
            "storage": {"mode": "rsync", "source_root": "/srv/criu", "destination_root": "/var/lib/clm"},
            "traffic": {
                "mode": "command",
                "hooks": {
                    "prepare": ["lbctl", "drain", "src.example"],
                    "switch": ["lbctl", "activate", "dst.example"],
                },
            },
        }

        request = core_config.clm_v1_to_migration_request(cfg)

        self.assertIsNone(request.container)
        self.assertEqual(request.container_group.name, "stack")
        self.assertEqual([item.identifier for item in request.container_group.containers], ["db", "web"])
        self.assertEqual(request.container_group.dependencies["web"], ("db",))
        self.assertEqual(request.runtime.type, "containerd")
        self.assertTrue(request.runtime.rootless)
        self.assertEqual(request.strategy, "pre-copy")
        self.assertEqual(request.storage.mode, "rsync")
        self.assertEqual(request.traffic.mode, "command")
        self.assertEqual(request.traffic.hooks["switch"], ["lbctl", "activate", "dst.example"])

    def test_clm_v1_validation_reports_shape_errors(self):
        errors = core_config.validate_clm_v1_config(
            {
                "version": 1,
                "source": "src.example",
                "destination": "dst.example",
                "container": {"id": "web"},
                "container_group": {"containers": ["db", "web"]},
                "runtime": {"privilege_mode": "admin"},
                "strategy": {"mode": "teleport"},
                "storage": {"mode": "sneakernet"},
                "traffic": {"mode": "magic"},
            }
        )

        self.assertTrue(any("exactly one" in error for error in errors))
        self.assertTrue(any("privilege_mode" in error for error in errors))
        self.assertTrue(any("Unknown migration strategy" in error for error in errors))
        self.assertTrue(any("storage.mode" in error for error in errors))
        self.assertTrue(any("traffic.mode" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
