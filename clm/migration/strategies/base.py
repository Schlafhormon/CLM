"""Migration strategy interface."""

from __future__ import annotations

import abc
from typing import Any, Optional

from clm.core.config import legacy_env_to_migration_request
from clm.core.models import MigrationPlan, MigrationRequest, MigrationResult, PreflightResult


class StrategySelectionError(ValueError):
    """Raised when a requested migration strategy is unknown."""


class MigrationStrategy(abc.ABC):
    """Plan, preflight, and run a migration strategy."""

    name: str
    legacy_method: Optional[str] = None

    @abc.abstractmethod
    def plan(self, source: dict[str, Any] | MigrationRequest, *, dry_run: bool = True) -> MigrationPlan:
        """Build a dry-run plan without side effects."""

    @abc.abstractmethod
    def preflight(self, source: dict[str, Any] | MigrationRequest) -> PreflightResult:
        """Validate whether the strategy can run."""

    @abc.abstractmethod
    def run(
        self,
        config: dict[str, Any],
        *,
        run_id: str,
        events_log: str,
        migrate_log: str,
    ) -> MigrationResult:
        """Execute the strategy."""

    def _request_from_source(self, source: dict[str, Any] | MigrationRequest) -> MigrationRequest:
        if isinstance(source, MigrationRequest):
            return source
        if isinstance(source, dict):
            return legacy_env_to_migration_request(source, method=self.legacy_method or self.name)
        raise TypeError(f"cannot build migration request from {type(source).__name__}")


def canonical_strategy_name(value: Optional[str]) -> str:
    """Normalize user-facing strategy names."""

    if value is None or str(value).strip() == "":
        return "auto"
    text = str(value).strip().lower().replace("_", "-")
    aliases = {
        "auto": "auto",
        "automatic": "auto",
        "default": "auto",
        "safe": "stop-and-copy",
        "stop": "stop-and-copy",
        "stop-copy": "stop-and-copy",
        "stopandcopy": "stop-and-copy",
        "stop-and-copy": "stop-and-copy",
        "precopy": "pre-copy",
        "pre-copy": "pre-copy",
        "postcopy": "post-copy",
        "post-copy": "post-copy",
    }
    try:
        return aliases[text]
    except KeyError as exc:
        raise StrategySelectionError(f"Unknown migration strategy: {value}") from exc

