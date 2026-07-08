"""Conservative migration strategy selection."""

from __future__ import annotations

from typing import Any, Optional

from clm.core.models import MigrationRequest
from clm.migration.strategies.base import MigrationStrategy, canonical_strategy_name
from clm.migration.strategies.postcopy import PostCopyStrategy
from clm.migration.strategies.precopy import PreCopyStrategy
from clm.migration.strategies.stop_and_copy import StopAndCopyStrategy


def select_strategy(
    source: dict[str, Any] | MigrationRequest | None = None,
    *,
    requested: Optional[str] = None,
    allow_experimental_minimal_downtime: bool = False,
) -> MigrationStrategy:
    """Select a migration strategy.

    Automatic selection is deliberately conservative. It returns
    stop-and-copy unless the caller explicitly requests pre-copy/post-copy, or
    an experimental minimal-downtime flag is enabled.
    """

    explicit = requested or _strategy_from_source(source)
    canonical = canonical_strategy_name(explicit)
    if canonical == "pre-copy":
        return PreCopyStrategy()
    if canonical == "post-copy":
        return PostCopyStrategy()
    if canonical == "stop-and-copy":
        return StopAndCopyStrategy()

    experimental_enabled = allow_experimental_minimal_downtime or _experimental_minimal_downtime_enabled(source)
    if experimental_enabled and _minimal_downtime_requested(source):
        return PreCopyStrategy()
    return StopAndCopyStrategy()


def _strategy_from_source(source: dict[str, Any] | MigrationRequest | None) -> Optional[str]:
    if isinstance(source, MigrationRequest):
        return source.strategy
    if not isinstance(source, dict):
        return None
    migration = source.get("migration") or {}
    strategy = migration.get("strategy") or source.get("strategy")
    if strategy:
        return str(strategy)
    method = migration.get("method") or source.get("method")
    return str(method) if method else None


def _minimal_downtime_requested(source: dict[str, Any] | MigrationRequest | None) -> bool:
    if isinstance(source, MigrationRequest):
        return _as_bool(source.options.get("minimal_downtime")) or _experimental_minimal_downtime_enabled(source)
    if not isinstance(source, dict):
        return False
    migration = source.get("migration") or {}
    return (
        _as_bool(migration.get("minimal_downtime"))
        or _experimental_minimal_downtime_enabled(source)
        or _as_bool(source.get("minimal_downtime"))
    )


def _experimental_minimal_downtime_enabled(source: dict[str, Any] | MigrationRequest | None) -> bool:
    if isinstance(source, MigrationRequest):
        return _as_bool(source.options.get("experimental_minimal_downtime"))
    if not isinstance(source, dict):
        return False
    migration = source.get("migration") or {}
    return _as_bool(migration.get("experimental_minimal_downtime")) or _as_bool(source.get("experimental_minimal_downtime"))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
