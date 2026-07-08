"""Typed core data structures for migration orchestration.

These models are intentionally small. They describe operator intent and
orchestration results without depending on the current runc shell scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class HostRef:
    role: str
    host: str
    ip: Optional[str] = None
    user: Optional[str] = None
    port: Optional[int] = None
    local: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeRef:
    type: str = "runc"
    socket_path: Optional[str] = None
    api_path: Optional[str] = None
    privilege_mode: str = "rootful"
    rootless: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CriuRef:
    binary: str = "criu"
    version: Optional[str] = None
    features: tuple[str, ...] = field(default_factory=tuple)
    custom_build: Optional[str] = None
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", tuple(self.features or ()))


@dataclass(frozen=True)
class ContainerRef:
    identifier: str
    runtime: RuntimeRef = field(default_factory=RuntimeRef)
    image: Optional[str] = None
    bundle_path: Optional[str] = None
    namespace: Optional[str] = None
    project: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContainerGroupRef:
    name: Optional[str] = None
    containers: tuple[ContainerRef, ...] = field(default_factory=tuple)
    ordered: bool = True
    dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "containers", tuple(self.containers or ()))
        object.__setattr__(
            self,
            "dependencies",
            {str(k): tuple(v or ()) for k, v in (self.dependencies or {}).items()},
        )


@dataclass(frozen=True)
class StoragePlan:
    mode: str = "shared"
    share_root: Optional[str] = None
    runs_root: Optional[str] = None
    logs_root: Optional[str] = None
    image_mode: Optional[str] = None
    cleanup_policy: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrafficPlan:
    mode: str = "external"
    vip_addr: Optional[str] = None
    vip_cidr: Optional[str] = None
    port: Optional[int] = None
    interfaces: dict[str, str] = field(default_factory=dict)
    hooks: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeSpec:
    name: str
    type: str
    target: Optional[str] = None
    url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    command: tuple[str, ...] = field(default_factory=tuple)
    interval_ms: Optional[int] = None
    timeout_ms: Optional[int] = None
    required: bool = False
    expected_status: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", tuple(self.command or ()))


@dataclass(frozen=True)
class MigrationRequest:
    source: HostRef
    destination: HostRef
    monitor: Optional[HostRef] = None
    container: Optional[ContainerRef] = None
    container_group: Optional[ContainerGroupRef] = None
    runtime: RuntimeRef = field(default_factory=RuntimeRef)
    criu: CriuRef = field(default_factory=CriuRef)
    strategy: str = "stop-and-copy"
    storage: StoragePlan = field(default_factory=StoragePlan)
    traffic: TrafficPlan = field(default_factory=TrafficPlan)
    probes: tuple[ProbeSpec, ...] = field(default_factory=tuple)
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "probes", tuple(self.probes or ()))
        if self.container is None and self.container_group is None:
            raise ValueError("MigrationRequest requires a container or container_group")


@dataclass(frozen=True)
class MigrationPlan:
    request: MigrationRequest
    steps: tuple[str, ...] = field(default_factory=tuple)
    dry_run: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))


@dataclass(frozen=True)
class MigrationResult:
    migration_id: str
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    timings: dict[str, float] = field(default_factory=dict)
    downtime_ms: Optional[float] = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    artifacts: dict[str, Any] = field(default_factory=dict)
    phases: dict[str, Any] = field(default_factory=dict)
    traffic: dict[str, Any] = field(default_factory=dict)
    probe_readiness: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "phases", dict(self.phases or {}))
        object.__setattr__(self, "traffic", dict(self.traffic or {}))
        object.__setattr__(self, "probe_readiness", dict(self.probe_readiness or {}))

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "success", "succeeded")


@dataclass(frozen=True)
class PreflightResult:
    checks: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "blockers", tuple(self.blockers or ()))

    @property
    def ok(self) -> bool:
        if self.blockers:
            return False
        return all(bool(check.get("ok", False)) for check in self.checks)
