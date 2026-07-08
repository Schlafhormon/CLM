"""Traffic backend selection."""

from __future__ import annotations

from typing import Any

from clm.core.config import traffic_from_legacy_env
from clm.core.models import MigrationRequest, TrafficPlan
from clm.migration.traffic.base import (
    TrafficActionResult,
    TrafficBackend,
    TrafficBackendError,
    TrafficConfigError,
    UnsupportedTrafficBackendError,
)
from clm.migration.traffic.command import CommandTrafficBackend
from clm.migration.traffic.external import ExternalTrafficBackend
from clm.migration.traffic.vip import VipTrafficBackend


_BACKENDS = {
    "external": ExternalTrafficBackend,
    "none": ExternalTrafficBackend,
    "command": CommandTrafficBackend,
    "commands": CommandTrafficBackend,
    "vip": VipTrafficBackend,
}


def select_traffic_backend(source: dict[str, Any] | TrafficPlan | MigrationRequest | None = None) -> TrafficBackend:
    plan = _coerce_traffic_plan(source)
    key = str(plan.mode or "external").strip().lower().replace("_", "-")
    backend_cls = _BACKENDS.get(key)
    if backend_cls is None:
        raise UnsupportedTrafficBackendError(f"Unsupported traffic backend: {plan.mode}")
    return backend_cls(plan=plan)


def _coerce_traffic_plan(source: dict[str, Any] | TrafficPlan | MigrationRequest | None) -> TrafficPlan:
    if source is None:
        return TrafficPlan(mode="external")
    if isinstance(source, TrafficPlan):
        return source
    if isinstance(source, MigrationRequest):
        return source.traffic
    if isinstance(source, dict):
        return traffic_from_legacy_env(source)
    raise TypeError(f"cannot select traffic backend from {type(source).__name__}")


__all__ = [
    "CommandTrafficBackend",
    "ExternalTrafficBackend",
    "TrafficActionResult",
    "TrafficBackend",
    "TrafficBackendError",
    "TrafficConfigError",
    "UnsupportedTrafficBackendError",
    "VipTrafficBackend",
    "select_traffic_backend",
]
