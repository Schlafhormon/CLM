"""Docker runtime backend placeholder."""

from __future__ import annotations

from typing import Any, Optional

from clm.core.models import MigrationResult, PreflightResult, RuntimeRef
from clm.runtimes.base import MigrationNotImplementedError, RuntimeBackend, RuntimeInspection


class DockerBackend(RuntimeBackend):
    """Preflight/inspect skeleton for future Docker migration support."""

    name = "docker"

    def preflight(self, config: Optional[dict[str, Any]] = None) -> PreflightResult:
        socket_path = self.runtime.socket_path or ((config or {}).get("runtime") or {}).get("socket_path")
        return PreflightResult(
            checks=(
                {
                    "name": "runtime: docker selected",
                    "ok": True,
                    "detail": self.runtime.type,
                },
            ),
            warnings=("Docker migration execution is not implemented yet.",),
            metadata={"socket_path": socket_path},
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
                "migration_supported": False,
            },
            warnings=("Docker inspect integration is a skeleton.",),
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
        raise MigrationNotImplementedError("Docker runtime migration is not implemented yet")
