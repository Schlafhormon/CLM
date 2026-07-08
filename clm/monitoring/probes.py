"""Probe specifications for app readiness and migration monitoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from clm.core.probes import parse_probe_spec as parse_core_probe_spec


PROBE_TYPES = {"http", "tcp", "command"}
PROBE_TYPE_ALIASES = {
    "http": "http",
    "https": "http",
    "tcp": "tcp",
    "l4": "tcp",
    "command": "command",
    "cmd": "command",
}


@dataclass(frozen=True)
class ProbeSpec:
    """A single operator-facing probe definition.

    HTTP and TCP probes are the core monitor primitives. Command probes are
    intended for explicit app readiness checks or site-specific verification.
    """

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
    expected_statuses: tuple[int, ...] = (200,)
    expected_exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        probe_type = _normalize_probe_type(self.type)
        object.__setattr__(self, "type", probe_type)
        object.__setattr__(self, "name", str(self.name or probe_type))
        object.__setattr__(self, "command", _command_tuple(self.command))
        object.__setattr__(self, "expected_statuses", _int_tuple(self.expected_statuses) or (200,))
        object.__setattr__(self, "interval_ms", _positive_optional_int(self.interval_ms, "interval_ms"))
        object.__setattr__(self, "timeout_ms", _positive_optional_int(self.timeout_ms, "timeout_ms"))
        object.__setattr__(self, "port", _positive_optional_int(self.port, "port"))
        object.__setattr__(self, "expected_exit_code", int(self.expected_exit_code))
        self._validate()

    @classmethod
    def http(
        cls,
        name: str,
        url: str,
        *,
        required: bool = False,
        expected_statuses: tuple[int, ...] = (200,),
        interval_ms: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        target: Optional[str] = None,
    ) -> "ProbeSpec":
        return cls(
            name=name,
            type="http",
            target=target,
            url=url,
            required=required,
            expected_statuses=expected_statuses,
            interval_ms=interval_ms,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def tcp(
        cls,
        name: str,
        host: str,
        port: int,
        *,
        required: bool = False,
        interval_ms: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        target: Optional[str] = None,
    ) -> "ProbeSpec":
        return cls(
            name=name,
            type="tcp",
            target=target,
            host=host,
            port=port,
            required=required,
            interval_ms=interval_ms,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def command(
        cls,
        name: str,
        command: str | list[str] | tuple[str, ...],
        *,
        required: bool = False,
        expected_exit_code: int = 0,
        timeout_ms: Optional[int] = None,
        target: Optional[str] = None,
    ) -> "ProbeSpec":
        return cls(
            name=name,
            type="command",
            target=target,
            command=_command_tuple(command),
            required=required,
            expected_exit_code=expected_exit_code,
            timeout_ms=timeout_ms,
        )

    def _validate(self) -> None:
        if self.type == "http":
            if not self.url:
                raise ValueError(f"HTTP probe '{self.name}' requires url")
            if not str(self.url).startswith(("http://", "https://")):
                raise ValueError(f"HTTP probe '{self.name}' url must start with http:// or https://")
        elif self.type == "tcp":
            if not self.host:
                raise ValueError(f"TCP probe '{self.name}' requires host")
            if self.port is None:
                raise ValueError(f"TCP probe '{self.name}' requires port")
        elif self.type == "command":
            if not self.command:
                raise ValueError(f"command probe '{self.name}' requires command")
        else:  # pragma: no cover - guarded by _normalize_probe_type
            raise ValueError(f"unsupported probe type: {self.type}")

    def expected_status(self) -> Optional[int]:
        """Return the first expected HTTP status for legacy model adapters."""

        return self.expected_statuses[0] if self.expected_statuses else None

    def to_core_probe_spec(self):
        """Convert to the older core ProbeSpec without making core depend on monitoring."""

        from clm.core.models import ProbeSpec as CoreProbeSpec

        return CoreProbeSpec(
            name=self.name,
            type=self.type,
            target=self.target,
            url=self.url,
            host=self.host,
            port=self.port,
            command=self.command,
            interval_ms=self.interval_ms,
            timeout_ms=self.timeout_ms,
            required=self.required,
            expected_status=self.expected_status(),
            metadata={
                **self.metadata,
                "expected_statuses": self.expected_statuses,
                "expected_exit_code": self.expected_exit_code,
            },
        )


def parse_probe_specs(values: Any) -> tuple[ProbeSpec, ...]:
    """Parse a list or single probe mapping into validated ProbeSpec objects."""

    return tuple(parse_probe_spec(value) for value in _as_list(values))


def parse_probe_spec(value: Any) -> ProbeSpec:
    """Parse one probe spec from a mapping or return an existing ProbeSpec."""

    if isinstance(value, ProbeSpec):
        return value
    return core_probe_to_monitoring_probe(parse_core_probe_spec(value))


def core_probe_to_monitoring_probe(value: Any) -> ProbeSpec:
    """Convert a legacy core ProbeSpec-like object to the monitoring model."""

    if isinstance(value, ProbeSpec):
        return value
    metadata = dict(getattr(value, "metadata", {}) or {})
    expected_statuses = metadata.pop("expected_statuses", None)
    if expected_statuses is None:
        expected_status = getattr(value, "expected_status", None)
        expected_statuses = (expected_status,) if expected_status is not None else (200,)
    expected_exit_code = metadata.pop("expected_exit_code", 0)
    return ProbeSpec(
        name=getattr(value, "name"),
        type=getattr(value, "type"),
        target=getattr(value, "target", None),
        url=getattr(value, "url", None),
        host=getattr(value, "host", None),
        port=getattr(value, "port", None),
        command=getattr(value, "command", ()),
        interval_ms=getattr(value, "interval_ms", None),
        timeout_ms=getattr(value, "timeout_ms", None),
        required=bool(getattr(value, "required", False)),
        expected_statuses=expected_statuses,
        expected_exit_code=expected_exit_code,
        metadata=metadata,
    )


def _normalize_probe_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    probe_type = PROBE_TYPE_ALIASES.get(text)
    if probe_type not in PROBE_TYPES:
        raise ValueError(f"unsupported probe type: {value}")
    return probe_type


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "required"}
    return bool(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _int_tuple(value: Any) -> tuple[int, ...]:
    out = []
    for item in _as_list(value):
        if item is None or item == "":
            continue
        out.append(int(item))
    return tuple(out)


def _command_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in _as_list(value) if str(item))


def _positive_optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed
