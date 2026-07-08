"""Runtime backend selection."""

from __future__ import annotations

from typing import Any

from clm.core.models import MigrationRequest, RuntimeRef
from clm.runtimes.base import (
    MigrationNotImplementedError,
    RuntimeBackend,
    RuntimeBackendError,
    RuntimeInspection,
    UnsupportedRuntimeError,
)
from clm.runtimes.containerd import ContainerdBackend
from clm.runtimes.docker import DockerBackend
from clm.runtimes.runc import RuncBackend


_BACKENDS = {
    "runc": RuncBackend,
    "oci": RuncBackend,
    "docker": DockerBackend,
    "containerd": ContainerdBackend,
    "ctr": ContainerdBackend,
}


def runtime_ref_from_config(config: dict[str, Any] | None) -> RuntimeRef:
    """Derive a RuntimeRef from the legacy config dictionary."""

    cfg = config or {}
    runtime_cfg = dict(cfg.get("runtime") or {})
    container_cfg = cfg.get("container") or {}
    runtime_type = runtime_cfg.pop("type", None) or container_cfg.get("runtime") or "runc"
    rootless = _as_bool(runtime_cfg.pop("rootless", False))
    privilege_mode = runtime_cfg.pop("privilege_mode", None) or ("rootless" if rootless else "rootful")
    return RuntimeRef(
        type=str(runtime_type),
        socket_path=runtime_cfg.pop("socket_path", None),
        api_path=runtime_cfg.pop("api_path", None),
        privilege_mode=str(privilege_mode),
        rootless=rootless,
        options=runtime_cfg,
    )


def select_backend(source: dict[str, Any] | RuntimeRef | MigrationRequest | None = None) -> RuntimeBackend:
    """Select a runtime backend from config or RuntimeRef.

    Missing runtime configuration defaults to runc for compatibility with the
    existing lab runner.
    """

    runtime = _coerce_runtime_ref(source)
    key = _normalize_runtime_type(runtime.type)
    backend_cls = _BACKENDS.get(key)
    if backend_cls is None:
        raise UnsupportedRuntimeError(f"Unsupported runtime backend: {runtime.type}")
    return backend_cls(runtime=runtime)


def _coerce_runtime_ref(source: dict[str, Any] | RuntimeRef | MigrationRequest | None) -> RuntimeRef:
    if source is None:
        return RuntimeRef(type="runc")
    if isinstance(source, RuntimeRef):
        return source
    if isinstance(source, MigrationRequest):
        return source.runtime
    if isinstance(source, dict):
        return runtime_ref_from_config(source)
    raise TypeError(f"cannot select runtime backend from {type(source).__name__}")


def _normalize_runtime_type(runtime_type: str) -> str:
    return str(runtime_type or "runc").strip().lower().replace("_", "-")


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = [
    "ContainerdBackend",
    "DockerBackend",
    "MigrationNotImplementedError",
    "RuncBackend",
    "RuntimeBackend",
    "RuntimeBackendError",
    "RuntimeInspection",
    "UnsupportedRuntimeError",
    "runtime_ref_from_config",
    "select_backend",
]
