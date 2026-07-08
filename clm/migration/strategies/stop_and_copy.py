"""Stop-and-copy migration strategy skeleton."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from clm.core.models import MigrationPlan, MigrationResult, PreflightResult
from clm.migration.strategies.base import MigrationStrategy
from clm.runtimes.base import MigrationNotImplementedError


class StopAndCopyStrategy(MigrationStrategy):
    """Safe default strategy boundary.

    Execution is intentionally not implemented yet. Selecting this strategy is
    still useful for automatic planning because it avoids opting users into
    lower-downtime experimental paths.
    """

    name = "stop-and-copy"
    legacy_method = "stop-and-copy"

    def plan(self, source: dict[str, Any], *, dry_run: bool = True) -> MigrationPlan:
        request = self._request_from_source(source)
        return MigrationPlan(
            request=request,
            dry_run=dry_run,
            steps=(
                "stop source container",
                "create final CRIU checkpoint",
                "transfer checkpoint and runtime artifacts",
                "restore container on destination",
                "perform configured traffic handling",
            ),
            warnings=("stop-and-copy execution is a strategy skeleton and is not implemented yet.",),
            artifacts={"implemented": False},
        )

    def preflight(self, source: dict[str, Any]) -> PreflightResult:
        return PreflightResult(
            checks=(
                {
                    "name": "strategy: stop-and-copy selected",
                    "ok": True,
                    "detail": "safe automatic default",
                },
            ),
            blockers=("stop-and-copy execution is not implemented yet.",),
            metadata={"strategy": self.name, "implemented": False},
        )

    def run(
        self,
        config: dict[str, Any],
        *,
        run_id: str,
        events_log: str,
        migrate_log: str,
    ) -> MigrationResult:
        raise MigrationNotImplementedError("stop-and-copy strategy execution is not implemented yet")

