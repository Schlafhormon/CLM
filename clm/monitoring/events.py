"""Stable event and result structures for probe-oriented monitoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from clm.monitoring.probes import ProbeSpec, core_probe_to_monitoring_probe


EVENT_SCHEMA_VERSION = "clm.monitoring.v1"


@dataclass(frozen=True)
class TimelineEvent:
    """A migration timeline marker in monitor-clock milliseconds."""

    name: str
    timestamp_ms: int
    phase: Optional[str] = None
    host: Optional[str] = None
    clock_domain: str = "monitor"
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": EVENT_SCHEMA_VERSION,
            "event_type": "timeline",
            "name": self.name,
            "timestamp_ms": int(self.timestamp_ms),
            "phase": self.phase,
            "host": self.host,
            "clock_domain": self.clock_domain,
            "data": dict(self.data),
        }


@dataclass(frozen=True)
class DowntimeWindow:
    """A client-visible or probe-visible downtime window."""

    source: str
    start_ms: int
    end_ms: int
    probe_name: Optional[str] = None
    quality_flags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags or ()))
        if self.end_ms < self.start_ms:
            raise ValueError("downtime window end_ms must be >= start_ms")

    @property
    def duration_ms(self) -> int:
        return int(self.end_ms - self.start_ms)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": EVENT_SCHEMA_VERSION,
            "source": self.source,
            "probe_name": self.probe_name,
            "start_ms": int(self.start_ms),
            "end_ms": int(self.end_ms),
            "duration_ms": self.duration_ms,
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True)
class ProbeResult:
    """The stable result object emitted by any HTTP, TCP, or command probe."""

    probe: ProbeSpec
    status: str
    timestamp_ms: int
    duration_ms: Optional[float] = None
    http_status: Optional[int] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    output: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe", core_probe_to_monitoring_probe(self.probe))
        object.__setattr__(self, "status", str(self.status or "").lower())
        if self.status not in {"success", "failure", "error", "skipped"}:
            raise ValueError(f"unsupported probe result status: {self.status}")

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_event(self) -> "ProbeEvent":
        return ProbeEvent(
            probe_name=self.probe.name,
            probe_type=self.probe.type,
            timestamp_ms=self.timestamp_ms,
            status=self.status,
            ok=self.ok,
            duration_ms=self.duration_ms,
            http_status=self.http_status,
            exit_code=self.exit_code,
            error=self.error,
            data=dict(self.metadata),
        )

    def as_dict(self) -> dict[str, Any]:
        return self.to_event().as_dict()


@dataclass(frozen=True)
class ProbeEvent:
    """Serializable event form for probe results."""

    probe_name: str
    probe_type: str
    timestamp_ms: int
    status: str
    ok: bool
    duration_ms: Optional[float] = None
    http_status: Optional[int] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": EVENT_SCHEMA_VERSION,
            "event_type": "probe_result",
            "probe_name": self.probe_name,
            "probe_type": self.probe_type,
            "timestamp_ms": int(self.timestamp_ms),
            "status": self.status,
            "ok": bool(self.ok),
            "duration_ms": self.duration_ms,
            "http_status": self.http_status,
            "exit_code": self.exit_code,
            "error": self.error,
            "data": dict(self.data),
        }


@dataclass(frozen=True)
class AppReadinessResult:
    """Readiness gate result with clear fatal/non-fatal semantics."""

    required: bool
    status: str
    ready: bool
    results: tuple[ProbeResult, ...] = field(default_factory=tuple)
    failed_required: tuple[str, ...] = field(default_factory=tuple)
    failed_optional: tuple[str, ...] = field(default_factory=tuple)
    missing_required: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results or ()))
        object.__setattr__(self, "failed_required", tuple(self.failed_required or ()))
        object.__setattr__(self, "failed_optional", tuple(self.failed_optional or ()))
        object.__setattr__(self, "missing_required", tuple(self.missing_required or ()))

    @property
    def fatal(self) -> bool:
        return self.required and not self.ready

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": EVENT_SCHEMA_VERSION,
            "event_type": "app_readiness",
            "required": self.required,
            "status": self.status,
            "ready": self.ready,
            "fatal": self.fatal,
            "failed_required": list(self.failed_required),
            "failed_optional": list(self.failed_optional),
            "missing_required": list(self.missing_required),
            "results": [result.as_dict() for result in self.results],
        }


def evaluate_app_readiness(
    specs: Sequence[ProbeSpec],
    results: Sequence[ProbeResult],
) -> AppReadinessResult:
    """Evaluate configured app readiness without conflating optional failures.

    Required probes must have a successful latest result. Optional probes are
    reported as warnings and do not make the migration fatal.
    """

    normalized_specs = tuple(core_probe_to_monitoring_probe(spec) for spec in (specs or ()))
    normalized_results = tuple(results or ())
    latest_by_name = _latest_results_by_name(normalized_results)

    if not normalized_specs:
        return AppReadinessResult(required=False, status="skipped", ready=True, results=normalized_results)

    required_specs = tuple(spec for spec in normalized_specs if spec.required)
    required = bool(required_specs)
    failed_required = []
    missing_required = []
    failed_optional = []

    for spec in normalized_specs:
        result = latest_by_name.get(spec.name)
        if result is None:
            if spec.required:
                missing_required.append(spec.name)
            continue
        if result.ok:
            continue
        if spec.required:
            failed_required.append(spec.name)
        else:
            failed_optional.append(spec.name)

    if failed_required or missing_required:
        return AppReadinessResult(
            required=required,
            status="not_ready",
            ready=False,
            results=normalized_results,
            failed_required=tuple(failed_required),
            failed_optional=tuple(failed_optional),
            missing_required=tuple(missing_required),
        )
    if failed_optional:
        return AppReadinessResult(
            required=required,
            status="ready_with_warnings",
            ready=True,
            results=normalized_results,
            failed_optional=tuple(failed_optional),
        )
    return AppReadinessResult(required=required, status="ready", ready=True, results=normalized_results)


def _latest_results_by_name(results: Sequence[ProbeResult]) -> dict[str, ProbeResult]:
    latest: dict[str, ProbeResult] = {}
    for result in results or ():
        name = result.probe.name
        current = latest.get(name)
        if current is None or int(result.timestamp_ms) >= int(current.timestamp_ms):
            latest[name] = result
    return latest
