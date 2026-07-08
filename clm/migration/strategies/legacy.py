"""Legacy strategy adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from clm.core.models import MigrationPlan, MigrationResult, PreflightResult
from clm.migration.strategies.base import MigrationStrategy
from clm.runtimes import select_backend


class LegacyAdapterStrategy(MigrationStrategy):
    """Run an existing runtime backend migration as a strategy.

    The current runc pre-copy and post-copy behavior still lives in shell
    scripts behind RuncBackend. This adapter keeps that behavior intact while
    exposing the strategy interface.
    """

    name = "legacy-adapter"

    def __init__(self, *, name: str, legacy_method: str):
        self.name = name
        self.legacy_method = legacy_method

    def plan(self, source: dict[str, Any], *, dry_run: bool = True) -> MigrationPlan:
        request = self._request_from_source(source)
        return MigrationPlan(
            request=request,
            dry_run=dry_run,
            steps=(
                f"select runtime backend for {request.runtime.type}",
                f"delegate {self.name} execution to legacy {self.legacy_method} adapter",
                "run existing CRIU/runc shell orchestration",
                "collect legacy migration log and return code",
            ),
            warnings=(
                f"{self.name} is currently executed through the legacy script adapter.",
            ),
            artifacts={"legacy_method": self.legacy_method},
        )

    def preflight(self, source: dict[str, Any]) -> PreflightResult:
        backend = select_backend(source)
        runtime_result = backend.preflight(source if isinstance(source, dict) else None)
        return PreflightResult(
            checks=runtime_result.checks
            + (
                {
                    "name": f"strategy: {self.name} legacy adapter selected",
                    "ok": True,
                    "detail": self.legacy_method,
                },
            ),
            warnings=runtime_result.warnings
            + (
                f"{self.name} Python-native orchestration is not implemented; using legacy adapter.",
            ),
            blockers=runtime_result.blockers,
            metadata={**runtime_result.metadata, "strategy": self.name, "legacy_method": self.legacy_method},
        )

    def run(
        self,
        config: dict[str, Any],
        *,
        run_id: str,
        events_log: str,
        migrate_log: str,
    ) -> MigrationResult:
        started_at = datetime.now(timezone.utc)
        result = select_backend(config).migrate(
            config,
            method=self.legacy_method,
            run_id=run_id,
            events_log=events_log,
            migrate_log=migrate_log,
        )
        artifacts = dict(result.artifacts)
        artifacts.update({"strategy": self.name, "legacy_method": self.legacy_method})
        return MigrationResult(
            migration_id=result.migration_id,
            status=result.status,
            started_at=result.started_at or started_at,
            ended_at=result.ended_at,
            timings=result.timings,
            downtime_ms=result.downtime_ms,
            errors=result.errors,
            warnings=result.warnings
            + (
                f"{self.name} used the legacy {self.legacy_method} migration adapter.",
            ),
            artifacts=artifacts,
            phases=result.phases,
            traffic=result.traffic,
            probe_readiness=result.probe_readiness,
        )
