"""runc runtime backend.

This backend intentionally adapts the existing runc shell-script path instead
of rewriting checkpoint/restore orchestration in Python.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from clm.core.models import MigrationResult, PreflightResult
from clm.host import CommandBuilder
from clm.migration.storage import transfer_plan_for
from clm.migration.traffic import select_traffic_backend
from clm.runtimes.base import RuntimeBackend, RuntimeInspection


class RuncBackend(RuntimeBackend):
    """Adapter around the current runc migration scripts."""

    name = "runc"
    migration_supported = True

    def preflight(self, config: Optional[dict[str, Any]] = None) -> PreflightResult:
        container = ((config or {}).get("container") or {})
        return PreflightResult(
            checks=(
                {"name": "runtime: runc selected", "ok": True, "detail": self.runtime.type},
                {
                    "name": "runtime: runc bundle configured",
                    "ok": bool(container.get("bundle")),
                    "detail": container.get("bundle") or "missing container.bundle",
                },
            ),
            metadata={
                "migration_scripts": self.migration_script_names(),
                "legacy_scripts": self.legacy_script_names(),
            },
        )

    def inspect(
        self,
        container_id: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> RuntimeInspection:
        container = ((config or {}).get("container") or {})
        return RuntimeInspection(
            runtime=self.runtime,
            status="legacy-adapter",
            details={
                "container_id": container_id or container.get("name"),
                "bundle": container.get("bundle"),
                "migration_supported": True,
                "migration_scripts": self.migration_script_names(),
                "legacy_scripts": self.legacy_script_names(),
            },
        )

    def migrate(
        self,
        config: dict[str, Any],
        *,
        method: str,
        run_id: str,
        events_log: str,
        migrate_log: str,
    ) -> MigrationResult:
        import clm.cli as legacy_cli

        started_at = datetime.now(timezone.utc)
        src = legacy_cli.host_alias(config, "source")
        transfer = transfer_plan_for(config, method=method, run_id=run_id)
        if not transfer.implemented:
            message = transfer.warnings[0] if transfer.warnings else f"{transfer.mode} transfer is not implemented"
            return MigrationResult(
                migration_id=run_id,
                status="failed",
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                errors=(message,),
                artifacts={
                    "events_log": events_log,
                    "migrate_log": migrate_log,
                    "returncode": 2,
                    "transfer_mode": transfer.mode,
                    "transfer_implemented": False,
                },
                phases={
                    "transfer": {
                        "status": "failed",
                        "ok": False,
                        "mode": transfer.mode,
                        "implemented": False,
                        "returncode": 2,
                    }
                },
            )
        script = self.build_legacy_migration_script(
            config,
            method=method,
            run_id=run_id,
            events_log=events_log,
        )

        legacy_cli.ensure_dir(str(Path(migrate_log).parent))
        with open(migrate_log, "w", encoding="utf-8") as fp:
            result = legacy_cli.run_remote(src, script, check=False, stdout=fp, stderr=fp)

        events = _read_events(events_log)
        traffic = _traffic_result_from_events(
            events,
            returncode=result.returncode,
            fallback_mode=select_traffic_backend(config).mode,
            migrate_log=migrate_log,
        )
        probe_readiness = _probe_readiness_from_events(events, returncode=result.returncode)
        phases = _phase_results_from_events(
            events,
            returncode=result.returncode,
            traffic=traffic,
            probe_readiness=probe_readiness,
        )
        status = _status_from_structured_result(result.returncode, phases, traffic, probe_readiness)
        errors = () if result.returncode == 0 else (f"runc legacy migration exited with rc={result.returncode}",)
        return MigrationResult(
            migration_id=run_id,
            status=status,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
            errors=errors,
            artifacts={
                "events_log": events_log,
                "migrate_log": migrate_log,
                "returncode": result.returncode,
                "traffic_mode": traffic.get("mode"),
            },
            phases=phases,
            traffic=traffic,
            probe_readiness=probe_readiness,
        )

    def build_legacy_migration_script(self, config: dict[str, Any], *, method: str, run_id: str, events_log: str) -> str:
        import clm.cli as legacy_cli

        cfg = config
        dst_ip = legacy_cli.host_ip(cfg, "dest")
        dst_user = cfg["hosts"].get("dest", {}).get("user") or "benke2"
        container = cfg["container"]
        traffic = select_traffic_backend(cfg)
        traffic_env = traffic.script_env(cfg)
        port = traffic_env.get("VIP_PORT") or ((cfg.get("vip") or {}).get("port")) or ((cfg.get("traffic") or {}).get("port")) or 8080
        post = cfg["postcopy"]
        migration = cfg.get("migration", {})
        precopy = cfg.get("precopy", {})
        transfer = transfer_plan_for(cfg, method=method, run_id=run_id)
        health_url_dst = f"http://{dst_ip}:{port}/health"
        readiness_urls = legacy_cli._normalize_url_list(post.get("readiness_urls")) or [health_url_dst]
        warmup_urls = legacy_cli._normalize_url_list(post.get("warmup_urls")) or [
            f"http://{dst_ip}:{port}/ready",
            f"http://{dst_ip}:{port}/counter",
        ]

        env_vars: dict[str, Any] = {
            "REPO": legacy_cli.repo_path_remote(cfg),
            "RUN_ID": run_id,
            "MODE": "runc",
            "NAME": container["name"],
            "CP_NAME": legacy_cli.checkpoint_name_for_run(method, run_id),
            "RUNC_BUNDLE_SRC": container["bundle"],
            "RUNC_BUNDLE_DST": container["bundle"],
            "SRC_NFS_ROOT": transfer.source_root,
            "REMOTE_NFS_ROOT": transfer.remote_root,
            "DST_LOCAL_ROOT": transfer.destination_root,
            "DST_HOST": dst_ip,
            "DST_USER": dst_user,
            "HEALTH_URL_DST": health_url_dst,
            "TRAFFIC_PORT": port,
            "NET_MODE": migration.get("net_mode", "host"),
            "CONTAINER_IP_DST": migration.get("container_ip_dest", "172.18.0.5"),
            "LOG_DIR": cfg["paths"]["logs_root"],
            "EVENTS_LOG": events_log,
            "TCP_EST": precopy.get("tcp_established", 1),
            "PRE_DUMP_ROUNDS": precopy.get("pre_dump_rounds", 0),
            "PRECOPY_IMAGE_MODE": transfer.precopy_image_mode,
        }
        env_vars.update(traffic_env)
        if method == "postcopy":
            post_runtime = legacy_cli._resolve_postcopy_runtime_settings(post)
            src_forward_enable = post_runtime["src_forward_enable"] if traffic.mode == "vip" else 0
            env_vars.update(
                {
                    "LAZY_PORT": post["lazy_port"],
                    "SRC_LAZY_IP": post["src_lazy_ip"],
                    "POSTCOPY_SRC_FORWARD_ENABLE": src_forward_enable,
                    "POSTCOPY_SRC_FORWARD_MODE": post.get("src_forwarding_mode", "iptables_dnat"),
                    "POSTCOPY_SRC_FORWARD_TARGET_HOST": post.get("src_forwarding_target_host", dst_ip),
                    "POSTCOPY_SRC_FORWARD_TARGET_PORT": post.get("src_forwarding_target_port", port),
                    "POSTCOPY_READINESS_URLS": ",".join(readiness_urls),
                    "POSTCOPY_READINESS_STABLE_SUCCESSES": post_runtime["readiness_stable_successes"],
                    "POSTCOPY_READINESS_INTERVAL_MS": post.get("readiness_interval_ms", 200),
                    "POSTCOPY_READINESS_TIMEOUT_MS": post_runtime["readiness_timeout_ms"],
                    "POSTCOPY_PROBE_MAX_TIME_S": post.get("probe_max_time_s", 2),
                    "POSTCOPY_WARMUP_URLS": ",".join(warmup_urls),
                    "POSTCOPY_WARMUP_ROUNDS": post.get("warmup_rounds", 1),
                    "POSTCOPY_WARMUP_INTERVAL_MS": post.get("warmup_interval_ms", 0),
                    "POSTCOPY_WARMUP_MAX_DURATION_MS": post.get("warmup_max_duration_ms", 400),
                }
            )

        script_name = f"migrate_{'precopy' if method == 'precopy' else 'postcopy_lazy_pages'}.sh"
        return CommandBuilder.shell_script(env_vars, [f"bash \"$REPO/scripts/{script_name}\""]).render()

    @staticmethod
    def migration_script_names() -> tuple[str, str]:
        return (
            "scripts/migrate_precopy.sh",
            "scripts/migrate_postcopy_lazy_pages.sh",
        )

    @staticmethod
    def legacy_script_names() -> tuple[str, str]:
        return (
            "scripts/migrate_precopy_vip_cutover.sh",
            "scripts/migrate_postcopy_lazy_pages_vip_cutover.sh",
        )


def _read_events(events_log: str) -> list[dict[str, Any]]:
    path = Path(events_log)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
    except OSError:
        return []
    return events


def _event_names(events: list[dict[str, Any]]) -> set[str]:
    return {str(event.get("event") or "") for event in events}


def _first_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event") == name:
            return event
    return None


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return None


def _event_time(event: dict[str, Any] | None) -> Any:
    if not event:
        return None
    return event.get("ts_unix_ms") or event.get("ts_ms")


def _traffic_mode_from_log(migrate_log: str) -> str | None:
    path = Path(migrate_log)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"(?:^|\s)traffic_mode=([^\s]+)", text)
    return match.group(1) if match else None


def _traffic_result_from_events(
    events: list[dict[str, Any]],
    *,
    returncode: int,
    fallback_mode: str,
    migrate_log: str,
) -> dict[str, Any]:
    names = _event_names(events)
    config = _first_event(events, "traffic_config")
    mode = (
        (config or {}).get("mode")
        or _first_event_field(events, ("traffic_prepare_start", "traffic_switch_start", "traffic_verify_start"), "mode")
        or _traffic_mode_from_log(migrate_log)
        or fallback_mode
    )
    actions: dict[str, dict[str, Any]] = {}
    failed_action: str | None = None
    for action in ("prepare", "switch", "verify"):
        start_name = f"traffic_{action}_start"
        done_name = f"traffic_{action}_done"
        skipped_name = f"traffic_{action}_skipped"
        started = start_name in names
        done = done_name in names
        skipped = skipped_name in names
        action_mode = (
            (_last_event(events, done_name) or {}).get("mode")
            or (_last_event(events, skipped_name) or {}).get("mode")
            or (_last_event(events, start_name) or {}).get("mode")
            or mode
        )
        status = "ok" if done else "skipped" if skipped else "running" if started else "unknown"
        action_result: dict[str, Any] = {
            "action": action,
            "mode": action_mode,
            "status": status,
            "ok": done or skipped,
            "skipped": skipped,
            "started": started,
            "completed": done,
        }
        if started:
            action_result["started_at_ms"] = _event_time(_last_event(events, start_name))
        if done:
            done_event = _last_event(events, done_name) or {}
            action_result["ended_at_ms"] = _event_time(done_event)
            if "dur_ms" in done_event:
                action_result["duration_ms"] = done_event.get("dur_ms")
        if skipped:
            skipped_event = _last_event(events, skipped_name) or {}
            action_result["reason"] = skipped_event.get("reason")
        if returncode != 0 and started and not done and not skipped:
            action_result.update({"status": "failed", "ok": False, "returncode": returncode})
            failed_action = action
        actions[action] = action_result

    failed = failed_action is not None
    return {
        "mode": str(mode),
        "status": "failed" if failed else "ok" if returncode == 0 else "unknown",
        "ok": False if failed else True if returncode == 0 else None,
        "returncode": returncode,
        "failed_action": failed_action,
        "actions": actions,
    }


def _first_event_field(events: list[dict[str, Any]], names: tuple[str, ...], field: str) -> Any:
    for name in names:
        event = _first_event(events, name)
        if event and field in event:
            return event.get(field)
    return None


def _probe_readiness_from_events(events: list[dict[str, Any]], *, returncode: int) -> dict[str, Any]:
    names = _event_names(events)
    started = "dest_readiness_wait_start" in names
    ok = "dest_readiness_ok" in names
    if not started and not ok:
        return {}
    status = "ok" if ok else "failed" if returncode != 0 else "unknown"
    return {
        "name": "postcopy-destination-readiness",
        "required": True,
        "ready": bool(ok),
        "status": status,
        "ok": bool(ok),
        "started": started,
        "returncode": returncode if status == "failed" else None,
    }


def _phase_results_from_events(
    events: list[dict[str, Any]],
    *,
    returncode: int,
    traffic: dict[str, Any],
    probe_readiness: dict[str, Any],
) -> dict[str, Any]:
    names = _event_names(events)
    phases: dict[str, Any] = {
        "runtime": {
            "status": "ok" if returncode == 0 else "failed",
            "ok": returncode == 0,
            "returncode": returncode,
        },
        "script": {
            "status": "ok" if returncode == 0 else "failed",
            "ok": returncode == 0,
            "returncode": returncode,
        },
    }
    for phase in ("checkpoint", "transfer", "restore"):
        start_name = f"{phase}_start"
        done_name = f"{phase}_done"
        started = start_name in names
        done = done_name in names
        failed = returncode != 0 and started and not done
        phases[phase] = {
            "status": "failed" if failed else "ok" if done else "running" if started else "unknown",
            "ok": False if failed else True if done else None,
            "started": started,
            "completed": done,
        }
        if started:
            phases[phase]["started_at_ms"] = _event_time(_last_event(events, start_name))
        if done:
            phases[phase]["ended_at_ms"] = _event_time(_last_event(events, done_name))
        if failed:
            phases[phase]["returncode"] = returncode

    if traffic:
        phases["traffic"] = {
            "status": traffic.get("status"),
            "ok": traffic.get("ok"),
            "mode": traffic.get("mode"),
            "returncode": traffic.get("returncode"),
            "failed_action": traffic.get("failed_action"),
        }
    if probe_readiness:
        phases["probe_readiness"] = {
            "status": probe_readiness.get("status"),
            "ok": probe_readiness.get("ok"),
            "required": probe_readiness.get("required"),
            "returncode": probe_readiness.get("returncode"),
        }
    return phases


def _status_from_structured_result(
    returncode: int,
    phases: dict[str, Any],
    traffic: dict[str, Any],
    probe_readiness: dict[str, Any],
) -> str:
    if returncode == 0:
        return "ok"
    if probe_readiness.get("required") is True and probe_readiness.get("ok") is False:
        return "failed"
    restore = phases.get("restore") if isinstance(phases.get("restore"), dict) else {}
    if restore.get("ok") is True and traffic.get("ok") is False:
        return "partial"
    return "failed"
