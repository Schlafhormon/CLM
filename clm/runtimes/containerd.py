"""containerd runtime backend placeholder."""

from __future__ import annotations

from typing import Any, Optional

from clm.core.models import MigrationResult, PreflightResult
from clm.runtimes.base import MigrationNotImplementedError, RuntimeBackend, RuntimeInspection


class ContainerdBackend(RuntimeBackend):
    """Preflight/inspect skeleton for future containerd migration support."""

    name = "containerd"

    def preflight(self, config: Optional[dict[str, Any]] = None) -> PreflightResult:
        runtime_cfg = (config or {}).get("runtime") or {}
        socket_path = self.runtime.socket_path or runtime_cfg.get("socket_path")
        namespace = self.runtime.options.get("namespace") or runtime_cfg.get("namespace")
        return PreflightResult(
            checks=(
                {
                    "name": "runtime: containerd selected",
                    "ok": True,
                    "detail": self.runtime.type,
                },
            ),
            warnings=("containerd migration execution is not implemented yet.",),
            metadata={"socket_path": socket_path, "namespace": namespace},
        )

    def inspect(
        self,
        container_id: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> RuntimeInspection:
        return RuntimeInspection(
            runtime=self.runtime,
            status="placeholder",
            details={
                "container_id": container_id,
                "socket_path": self.runtime.socket_path,
                "namespace": self.runtime.options.get("namespace"),
                "migration_supported": False,
            },
            warnings=("containerd inspect integration is a skeleton.",),
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
        raise MigrationNotImplementedError("containerd runtime migration is not implemented yet")
