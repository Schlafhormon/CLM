"""Traffic cutover backend interfaces."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from clm.core.models import PreflightResult, TrafficPlan


class TrafficBackendError(RuntimeError):
    """Base error for traffic backend failures."""


class TrafficConfigError(TrafficBackendError, ValueError):
    """Raised when a traffic backend config is unsafe or invalid."""


class UnsupportedTrafficBackendError(TrafficBackendError):
    """Raised when no traffic backend exists for a mode."""


@dataclass(frozen=True)
class TrafficActionResult:
    """Result of one traffic backend phase."""

    action: str
    ok: bool = True
    skipped: bool = False
    message: str = ""
    returncode: Optional[int] = None
    details: dict[str, Any] = field(default_factory=dict)


class TrafficBackend(abc.ABC):
    """Interface for optional traffic handling around a migration."""

    mode: str

    def __init__(self, plan: Optional[TrafficPlan] = None):
        self.plan = plan or TrafficPlan(mode=self.mode)

    @abc.abstractmethod
    def preflight(self, context: Optional[Mapping[str, Any]] = None) -> PreflightResult:
        """Validate backend configuration before migration."""

    @abc.abstractmethod
    def prepare(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        """Prepare destination/source traffic state before restore."""

    @abc.abstractmethod
    def switch(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        """Switch traffic after destination restore is ready."""

    @abc.abstractmethod
    def verify(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        """Verify traffic handling after switch."""

    def rollback(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        """Optionally roll back a failed switch."""

        return TrafficActionResult(
            action="rollback",
            ok=True,
            skipped=True,
            message=f"{self.mode} traffic backend has no rollback hook",
        )

    def script_env(self, config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Return environment variables consumed by legacy migration scripts."""

        return {"TRAFFIC_MODE": self.mode}


def noop_result(action: str, message: str) -> TrafficActionResult:
    return TrafficActionResult(action=action, ok=True, skipped=True, message=message)
