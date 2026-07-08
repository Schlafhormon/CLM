"""Runtime backend interfaces.

Runtime backends describe how CLM talks to a container runtime. The current
orchestration still delegates runc migration to legacy shell scripts; this
module defines the boundary new runtime implementations should implement.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional

from clm.core.models import MigrationResult, PreflightResult, RuntimeRef


class RuntimeBackendError(RuntimeError):
    """Base error for runtime backend failures."""


class UnsupportedRuntimeError(RuntimeBackendError):
    """Raised when no backend exists for a runtime reference."""


class MigrationNotImplementedError(RuntimeBackendError, NotImplementedError):
    """Raised when a backend is known but cannot run migrations yet."""


@dataclass(frozen=True)
class RuntimeInspection:
    """Small runtime inspection payload returned by backend skeletons."""

    runtime: RuntimeRef
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))


class RuntimeBackend(abc.ABC):
    """Interface implemented by container runtime adapters."""

    name: str
    migration_supported: bool = False

    def __init__(self, runtime: Optional[RuntimeRef] = None):
        self.runtime = runtime or RuntimeRef(type=self.name)

    @abc.abstractmethod
    def preflight(self, config: Optional[dict[str, Any]] = None) -> PreflightResult:
        """Return runtime-specific preflight checks."""

    @abc.abstractmethod
    def inspect(
        self,
        container_id: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> RuntimeInspection:
        """Inspect runtime/container state without starting a migration."""

    @abc.abstractmethod
    def migrate(
        self,
        config: dict[str, Any],
        *,
        method: str,
        run_id: str,
        events_log: str,
        migrate_log: str,
    ) -> MigrationResult:
        """Execute a migration and return a structured result."""
