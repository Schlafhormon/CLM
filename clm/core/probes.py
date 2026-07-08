"""Runtime-neutral probe parsing helpers for core configuration."""

from __future__ import annotations

from typing import Any, Optional

from clm.core.models import ProbeSpec


PROBE_TYPES = {"http", "tcp", "command"}
PROBE_TYPE_ALIASES = {
    "http": "http",
    "https": "http",
    "tcp": "tcp",
    "l4": "tcp",
    "command": "command",
    "cmd": "command",
}


def parse_probe_specs(values: Any) -> tuple[ProbeSpec, ...]:
    """Parse a list or single probe mapping into validated core ProbeSpec objects."""

    return tuple(parse_probe_spec(value) for value in _as_list(values))


def parse_probe_spec(value: Any) -> ProbeSpec:
    """Parse one probe spec from a mapping or return an existing core ProbeSpec."""

    if isinstance(value, ProbeSpec):
        return value
    if not isinstance(value, dict):
        raise ValueError("probe entries must be mappings")

    cfg = dict(value)
    probe_type = normalize_probe_type(cfg.pop("type", cfg.pop("kind", "http")))
    expected_statuses = cfg.pop("expected_statuses", None)
    expected_status = cfg.pop("expected_status", None)
    if expected_statuses is None and expected_status is not None:
        expected_statuses = (expected_status,)
    expected_status_tuple = int_tuple(expected_statuses) or (200,)
    expected_exit_code = int(cfg.pop("expected_exit_code", 0))

    spec = ProbeSpec(
        name=str(cfg.pop("name", probe_type)),
        type=probe_type,
        target=cfg.pop("target", None),
        url=cfg.pop("url", None),
        host=cfg.pop("host", None),
        port=positive_optional_int(cfg.pop("port", None), "port"),
        command=command_tuple(cfg.pop("command", ())),
        interval_ms=positive_optional_int(cfg.pop("interval_ms", None), "interval_ms"),
        timeout_ms=positive_optional_int(cfg.pop("timeout_ms", None), "timeout_ms"),
        required=as_bool(cfg.pop("required", False)),
        expected_status=expected_status_tuple[0] if expected_status_tuple else None,
        metadata={
            **cfg,
            "expected_statuses": expected_status_tuple,
            "expected_exit_code": expected_exit_code,
        },
    )
    validate_probe_spec(spec)
    return spec


def validate_probe_spec(spec: ProbeSpec) -> None:
    """Validate HTTP, TCP, and command probe requirements."""

    if spec.type == "http":
        if not spec.url:
            raise ValueError(f"HTTP probe '{spec.name}' requires url")
        if not str(spec.url).startswith(("http://", "https://")):
            raise ValueError(f"HTTP probe '{spec.name}' url must start with http:// or https://")
    elif spec.type == "tcp":
        if not spec.host:
            raise ValueError(f"TCP probe '{spec.name}' requires host")
        if spec.port is None:
            raise ValueError(f"TCP probe '{spec.name}' requires port")
    elif spec.type == "command":
        if not spec.command:
            raise ValueError(f"command probe '{spec.name}' requires command")
    else:
        raise ValueError(f"unsupported probe type: {spec.type}")


def normalize_probe_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    probe_type = PROBE_TYPE_ALIASES.get(text)
    if probe_type not in PROBE_TYPES:
        raise ValueError(f"unsupported probe type: {value}")
    return probe_type


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "required"}
    return bool(value)


def as_list(value: Any) -> list[Any]:
    return _as_list(value)


def int_tuple(value: Any) -> tuple[int, ...]:
    out = []
    for item in _as_list(value):
        if item is None or item == "":
            continue
        out.append(int(item))
    return tuple(out)


def command_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in _as_list(value) if str(item))


def positive_optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


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
