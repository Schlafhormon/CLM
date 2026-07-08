"""runc runtime backend.

This backend intentionally adapts the existing runc shell-script path instead
of rewriting checkpoint/restore orchestration in Python.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from clm.core.models import MigrationResult, PreflightResult
from clm.runtimes.base import RuntimeBackend, RuntimeInspection


class RuncBackend(RuntimeBackend):
    """Adapter around the current runc migration scripts."""

    name = "runc"

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
            metadata={"legacy_scripts": self.legacy_script_names()},
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
        script = self.build_legacy_migration_script(
            config,
            method=method,
            run_id=run_id,
            events_log=events_log,
        )

        legacy_cli.ensure_dir(str(Path(migrate_log).parent))
        with open(migrate_log, "w", encoding="utf-8") as fp:
            result = legacy_cli.run_remote(src, script, check=False, stdout=fp, stderr=fp)

        status = "ok" if result.returncode == 0 else "failed"
        errors = () if result.returncode == 0 else (f"runc legacy migration exited with rc={result.returncode}",)
        return MigrationResult(
            migration_id=run_id,
            status=status,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
            errors=errors,
            artifacts={"events_log": events_log, "migrate_log": migrate_log, "returncode": result.returncode},
        )

    def build_legacy_migration_script(self, config: dict[str, Any], *, method: str, run_id: str, events_log: str) -> str:
        import clm.cli as legacy_cli

        cfg = config
        dst_ip = legacy_cli.host_ip(cfg, "dest")
        dst_user = cfg["hosts"].get("dest", {}).get("user") or "benke2"
        container = cfg["container"]
        vip = cfg["vip"]
        post = cfg["postcopy"]
        migration = cfg.get("migration", {})
        precopy = cfg.get("precopy", {})
        health_url_dst = f"http://{dst_ip}:{vip['port']}/health"
        readiness_urls = legacy_cli._normalize_url_list(post.get("readiness_urls")) or [health_url_dst]
        warmup_urls = legacy_cli._normalize_url_list(post.get("warmup_urls")) or [
            f"http://{dst_ip}:{vip['port']}/ready",
            f"http://{dst_ip}:{vip['port']}/counter",
        ]
        vip_conntrack_clear_src = migration.get("vip_conntrack_clear_src", 0)
        if isinstance(vip_conntrack_clear_src, str):
            vip_conntrack_clear_src = 1 if vip_conntrack_clear_src.strip().lower() in ("1", "true", "yes", "on") else 0
        else:
            vip_conntrack_clear_src = 1 if bool(vip_conntrack_clear_src) else 0

        env_vars: dict[str, Any] = {
            "REPO": legacy_cli.repo_path_remote(cfg),
            "RUN_ID": run_id,
            "MODE": "runc",
            "NAME": container["name"],
            "CP_NAME": legacy_cli.checkpoint_name_for_run(method, run_id),
            "RUNC_BUNDLE_SRC": container["bundle"],
            "RUNC_BUNDLE_DST": container["bundle"],
            "SRC_NFS_ROOT": cfg["paths"]["share_root"],
            "REMOTE_NFS_ROOT": cfg["paths"]["share_root"],
            "DST_LOCAL_ROOT": "/var/lib/criu-local",
            "DST_HOST": dst_ip,
            "DST_USER": dst_user,
            "HEALTH_URL_DST": health_url_dst,
            "VIP_ADDR": vip["addr"],
            "VIP_CIDR": vip["cidr"],
            "VIP_IF_SRC": vip["if_source"],
            "VIP_IF_DST": vip["if_dest"],
            "VIP_PORT": vip["port"],
            "NET_MODE": migration.get("net_mode", "host"),
            "CONTAINER_IP_DST": migration.get("container_ip_dest", "172.18.0.5"),
            "VIP_GARP_COUNT": migration.get("vip_garp_count", 3),
            "VIP_GARP_INTERVAL_MS": migration.get("vip_garp_interval_ms", 200),
            "VIP_GARP_MODE": migration.get("vip_garp_mode", "A"),
            "VIP_CONNTRACK_CLEAR_SRC": vip_conntrack_clear_src,
            "LOG_DIR": cfg["paths"]["logs_root"],
            "EVENTS_LOG": events_log,
            "TCP_EST": precopy.get("tcp_established", 1),
            "PRE_DUMP_ROUNDS": precopy.get("pre_dump_rounds", 0),
            "PRECOPY_IMAGE_MODE": precopy.get("image_mode", "shared"),
        }
        if method == "postcopy":
            post_runtime = legacy_cli._resolve_postcopy_runtime_settings(post)
            env_vars.update(
                {
                    "LAZY_PORT": post["lazy_port"],
                    "SRC_LAZY_IP": post["src_lazy_ip"],
                    "POSTCOPY_SRC_FORWARD_ENABLE": post_runtime["src_forward_enable"],
                    "POSTCOPY_SRC_FORWARD_MODE": post.get("src_forwarding_mode", "iptables_dnat"),
                    "POSTCOPY_SRC_FORWARD_TARGET_HOST": post.get("src_forwarding_target_host", dst_ip),
                    "POSTCOPY_SRC_FORWARD_TARGET_PORT": post.get("src_forwarding_target_port", vip["port"]),
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

        script_name = f"migrate_{'precopy' if method == 'precopy' else 'postcopy_lazy_pages'}_vip_cutover.sh"
        return legacy_cli.build_remote_script(env_vars, [f"bash \"$REPO/scripts/{script_name}\""])

    @staticmethod
    def legacy_script_names() -> tuple[str, str]:
        return (
            "scripts/migrate_precopy_vip_cutover.sh",
            "scripts/migrate_postcopy_lazy_pages_vip_cutover.sh",
        )
