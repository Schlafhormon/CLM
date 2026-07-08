#!/usr/bin/env python3

import tempfile
import unittest
import shlex
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
        self.assertIn("bash \"$REPO/scripts/migrate_precopy.sh\"", captured["script"])

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
        self.assertIn("export TRAFFIC_PORT=8080", script)
        self.assertIn("export TRAFFIC_PREPARE_CMD='lbctl drain source'", script)
        self.assertIn("export TRAFFIC_SWITCH_CMD='lbctl activate dest'", script)
        self.assertIn("export TRAFFIC_VERIFY_CMD='curl -fsS http://service/health'", script)
        for vip_env in ("VIP_ADDR", "VIP_CIDR", "VIP_IF_SRC", "VIP_IF_DST", "VIP_PORT", "VIP_CONNTRACK_CLEAR_SRC"):
            self.assertNotIn(f"export {vip_env}", script)

    def test_runc_backend_external_traffic_does_not_export_vip_cutover_env(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["traffic"] = {
            "mode": "external",
            "hooks": {"verify": ["curl", "-fsS", "http://service/health"]},
        }

        script = RuncBackend().build_legacy_migration_script(
            cfg,
            method="precopy",
            run_id="run-external",
            events_log="/tmp/events.ndjson",
        )

        self.assertIn("export TRAFFIC_MODE=external", script)
        self.assertIn("export TRAFFIC_PORT=8080", script)
        self.assertIn("export TRAFFIC_VERIFY_CMD='curl -fsS http://service/health'", script)
        for vip_env in ("VIP_ADDR", "VIP_CIDR", "VIP_IF_SRC", "VIP_IF_DST", "VIP_PORT", "VIP_CONNTRACK_CLEAR_SRC"):
            self.assertNotIn(f"export {vip_env}", script)

    def test_runc_backend_quotes_hook_arguments_and_env_values(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM Repo"
        cfg["container"]["name"] = "web app"
        cfg["traffic"] = {
            "mode": "command",
            "hooks": {
                "switch": ["lbctl", "activate dest", "name=web app", "quote'arg"],
            },
        }
        cfg["paths"]["logs_root"] = "/mnt/criu/logs with space"

        script = RuncBackend().build_legacy_migration_script(
            cfg,
            method="precopy",
            run_id="run with quote'",
            events_log="/tmp/events log\nnext.ndjson",
        )

        self.assertIn("export REPO=${HOME}'/CLM Repo'", script)
        self.assertIn("export NAME='web app'", script)
        self.assertIn("export RUN_ID='run with quote'\"'\"''", script)
        self.assertIn("export EVENTS_LOG='/tmp/events log\nnext.ndjson'", script)
        hook = shlex.join(["lbctl", "activate dest", "name=web app", "quote'arg"])
        self.assertIn(f"export TRAFFIC_SWITCH_CMD={shlex.quote(hook)}", script)

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


class RuncMigrationScriptTests(unittest.TestCase):
    scripts = (
        Path("scripts/migrate_precopy_vip_cutover.sh"),
        Path("scripts/migrate_postcopy_lazy_pages_vip_cutover.sh"),
    )
    blocked_segments = ("ip addr add", "ip addr del", "conntrack -D", "arping")

    def test_neutral_entrypoint_wrappers_delegate_to_legacy_scripts(self):
        wrappers = {
            Path("scripts/migrate_precopy.sh"): "migrate_precopy_vip_cutover.sh",
            Path("scripts/migrate_postcopy_lazy_pages.sh"): "migrate_postcopy_lazy_pages_vip_cutover.sh",
        }

        for wrapper, legacy_name in wrappers.items():
            text = wrapper.read_text(encoding="utf-8")
            self.assertIn(legacy_name, text)

    def test_external_and_command_traffic_cases_do_not_run_vip_side_effects(self):
        for script in self.scripts:
            text = script.read_text(encoding="utf-8")
            for function in ("traffic_prepare", "traffic_switch", "traffic_verify"):
                body = _bash_function_body(text, function)
                for mode in ("external", "command"):
                    arm = _traffic_mode_case_arm(body, mode)
                    for segment in self.blocked_segments:
                        self.assertNotIn(segment, arm, f"{script}:{function}:{mode} contains {segment}")


def _bash_function_body(script: str, name: str) -> str:
    marker = f"{name}()"
    start = script.find(marker)
    if start < 0:
        marker = f"{name}(){{"
        start = script.find(marker)
    if start < 0:
        raise AssertionError(f"missing bash function {name}")
    brace_start = script.find("{", start)
    end = script.find("\n}", brace_start)
    if end >= 0:
        return script[brace_start + 1 : end]
    raise AssertionError(f"unterminated bash function {name}")


def _traffic_mode_case_arm(function_body: str, mode: str) -> str:
    lines = function_body.splitlines()
    in_case = False
    capture = False
    captured: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == 'case "$TRAFFIC_MODE" in':
            in_case = True
            continue
        if not in_case:
            continue
        if stripped.endswith(")") and not stripped.startswith(("if ", "for ", "while ")):
            labels = stripped[:-1].split("|")
            if capture:
                break
            capture = mode in labels
            continue
        if capture:
            if stripped == ";;":
                break
            captured.append(line)
    if not captured:
        raise AssertionError(f"missing TRAFFIC_MODE={mode} arm")
    return "\n".join(captured)


if __name__ == "__main__":
    unittest.main()
