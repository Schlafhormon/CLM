"""Config loading and model derivation helpers.

The current CLI still consumes the legacy env.yaml dictionary directly. This
module keeps that structure loadable while exposing typed core models for new
orchestration code.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from clm.core.models import (
    ContainerGroupRef,
    ContainerRef,
    CriuRef,
    HostRef,
    MigrationRequest,
    ProbeSpec,
    RuntimeRef,
    StoragePlan,
    TrafficPlan,
)

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


LOCAL_HOSTS = {"local", "localhost", "127.0.0.1", "::1", ""}


def legacy_defaults() -> dict[str, Any]:
    """Return a copy of the legacy CLI defaults."""

    from clm.cli import DEFAULTS

    return deepcopy(DEFAULTS)


def deep_merge(base: dict[str, Any], override: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Recursively merge dictionaries without mutating inputs."""

    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def normalize_hosts(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy host entries to role dictionaries."""

    cfg = deepcopy(config)
    hosts = cfg.get("hosts") or {}
    normalized = {}
    for role in ("monitor", "source", "dest"):
        entry = hosts.get(role)
        if isinstance(entry, str):
            normalized[role] = {"host": entry}
        elif isinstance(entry, dict):
            normalized[role] = deepcopy(entry)
        else:
            normalized[role] = {}
    cfg["hosts"] = normalized
    return cfg


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML object from disk."""

    if yaml is None:
        raise RuntimeError("PyYAML is required to load CLM config files")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a YAML object: {p}")
    return data


def load_legacy_env(path: str | Path, defaults: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Load the existing env.yaml format into a compatibility dictionary."""

    data = load_yaml_file(path)
    cfg = deep_merge(legacy_defaults() if defaults is None else defaults, data)
    cfg = normalize_hosts(cfg)

    paths = cfg.setdefault("paths", {})
    share_root = paths.get("share_root") or "/mnt/criu"
    paths.setdefault("runs_root", f"{share_root}/runs")
    paths.setdefault("logs_root", f"{share_root}/logs")

    postcopy = cfg.setdefault("postcopy", {})
    if not postcopy.get("src_lazy_ip"):
        postcopy["src_lazy_ip"] = (cfg.get("hosts") or {}).get("source", {}).get("ip") or "192.168.13.10"
    return cfg


def load_env(path: str | Path, defaults: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Compatibility alias for callers that expect an env loader."""

    return load_legacy_env(path, defaults=defaults)


def load_migration_request(path: str | Path, method: Optional[str] = None) -> MigrationRequest:
    """Load legacy env.yaml and derive the first core MigrationRequest."""

    return legacy_env_to_migration_request(load_legacy_env(path), method=method)


def legacy_env_to_migration_request(config: dict[str, Any], method: Optional[str] = None) -> MigrationRequest:
    """Derive core migration intent from legacy env.yaml data."""

    cfg = normalize_hosts(config)
    runtime = runtime_from_legacy_env(cfg)
    container = container_from_legacy_env(cfg, runtime=runtime)
    container_group = container_group_from_config(cfg, runtime=runtime)
    strategy = _strategy_from_method(method or (cfg.get("migration") or {}).get("strategy"))
    return MigrationRequest(
        source=host_from_legacy_env(cfg, "source"),
        destination=host_from_legacy_env(cfg, "dest"),
        monitor=host_from_legacy_env(cfg, "monitor"),
        container=None if container_group is not None else container,
        container_group=container_group,
        runtime=runtime,
        criu=criu_from_legacy_env(cfg),
        strategy=strategy,
        storage=storage_from_legacy_env(cfg),
        traffic=traffic_from_legacy_env(cfg),
        probes=tuple(probes_from_legacy_env(cfg)),
        options={
            "legacy_migration": deepcopy(cfg.get("migration") or {}),
            "legacy_precopy": deepcopy(cfg.get("precopy") or {}),
            "legacy_postcopy": deepcopy(cfg.get("postcopy") or {}),
            "legacy_monitor": deepcopy(cfg.get("monitor") or {}),
        },
    )


build_migration_request = legacy_env_to_migration_request


def host_from_legacy_env(config: dict[str, Any], role: str) -> HostRef:
    hosts = (config.get("hosts") or {})
    entry = hosts.get(role) or {}
    if isinstance(entry, str):
        entry = {"host": entry}
    host = str(entry.get("host") or "")
    return HostRef(
        role=role,
        host=host,
        ip=entry.get("ip"),
        user=entry.get("user"),
        port=_optional_int(entry.get("port")),
        local=host in LOCAL_HOSTS,
        metadata={k: deepcopy(v) for k, v in entry.items() if k not in {"host", "ip", "user", "port"}},
    )


def runtime_from_legacy_env(config: dict[str, Any]) -> RuntimeRef:
    runtime_cfg = deepcopy(config.get("runtime") or {})
    container_cfg = config.get("container") or {}
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


def criu_from_legacy_env(config: dict[str, Any]) -> CriuRef:
    criu_cfg = deepcopy(config.get("criu") or {})
    features = criu_cfg.pop("features", ())
    return CriuRef(
        binary=str(criu_cfg.pop("binary", "criu")),
        version=criu_cfg.pop("version", None),
        features=_as_str_tuple(features),
        custom_build=criu_cfg.pop("custom_build", None),
        options=criu_cfg,
    )


def container_from_legacy_env(config: dict[str, Any], runtime: Optional[RuntimeRef] = None) -> ContainerRef:
    container_cfg = deepcopy(config.get("container") or {})
    runtime_ref = runtime or runtime_from_legacy_env(config)
    return ContainerRef(
        identifier=str(container_cfg.pop("name", "testweb")),
        runtime=runtime_ref,
        image=container_cfg.pop("image", None),
        bundle_path=container_cfg.pop("bundle", None),
        namespace=container_cfg.pop("namespace", None),
        project=container_cfg.pop("project", None),
        metadata=container_cfg,
    )


def container_group_from_config(
    config: dict[str, Any],
    runtime: Optional[RuntimeRef] = None,
) -> Optional[ContainerGroupRef]:
    group_cfg = config.get("container_group")
    if not group_cfg:
        return None
    runtime_ref = runtime or runtime_from_legacy_env(config)
    if isinstance(group_cfg, list):
        raw_containers = group_cfg
        name = None
        ordered = True
        dependencies = {}
        metadata = {}
    elif isinstance(group_cfg, dict):
        raw_containers = group_cfg.get("containers") or []
        name = group_cfg.get("name")
        ordered = _as_bool(group_cfg.get("ordered", True))
        dependencies = group_cfg.get("dependencies") or {}
        metadata = {k: deepcopy(v) for k, v in group_cfg.items() if k not in {"name", "ordered", "dependencies", "containers"}}
    else:
        raise ValueError("container_group must be a list or mapping")

    containers = []
    for item in raw_containers:
        if isinstance(item, str):
            containers.append(ContainerRef(identifier=item, runtime=runtime_ref))
        elif isinstance(item, dict):
            item_cfg = {"container": item, "runtime": config.get("runtime") or {}}
            containers.append(container_from_legacy_env(item_cfg, runtime=runtime_ref))
        else:
            raise ValueError("container_group containers must be strings or mappings")
    return ContainerGroupRef(
        name=name,
        containers=tuple(containers),
        ordered=ordered,
        dependencies={str(k): _as_str_tuple(v) for k, v in dependencies.items()},
        metadata=metadata,
    )


def storage_from_legacy_env(config: dict[str, Any]) -> StoragePlan:
    storage_cfg = deepcopy(config.get("storage") or {})
    paths = config.get("paths") or {}
    precopy = config.get("precopy") or {}
    cleanup = config.get("cleanup") or {}
    image_mode = storage_cfg.pop("image_mode", None) or precopy.get("image_mode")
    mode = storage_cfg.pop("mode", None) or ("shared" if image_mode in (None, "shared") else str(image_mode))
    return StoragePlan(
        mode=str(mode),
        share_root=storage_cfg.pop("share_root", None) or paths.get("share_root"),
        runs_root=storage_cfg.pop("runs_root", None) or paths.get("runs_root"),
        logs_root=storage_cfg.pop("logs_root", None) or paths.get("logs_root"),
        image_mode=image_mode,
        cleanup_policy=deepcopy(cleanup),
        options=storage_cfg,
    )


def traffic_from_legacy_env(config: dict[str, Any]) -> TrafficPlan:
    traffic_cfg = deepcopy(config.get("traffic") or {})
    vip = config.get("vip") or {}
    nested_vip = deepcopy(traffic_cfg.pop("vip", {}) or {})
    if traffic_cfg:
        mode = str(traffic_cfg.pop("mode", "external"))
        hooks = deepcopy(traffic_cfg.pop("hooks", {}))
    elif vip:
        mode = "vip"
        hooks = {}
    else:
        mode = "external"
        hooks = {}
    return TrafficPlan(
        mode=mode,
        vip_addr=traffic_cfg.pop("vip_addr", None) or nested_vip.get("addr") or vip.get("addr"),
        vip_cidr=traffic_cfg.pop("vip_cidr", None) or nested_vip.get("cidr") or vip.get("cidr"),
        port=_optional_int(traffic_cfg.pop("port", None) or nested_vip.get("port") or vip.get("port")),
        interfaces={
            "source": str(traffic_cfg.pop("if_source", None) or nested_vip.get("if_source") or vip.get("if_source") or ""),
            "dest": str(traffic_cfg.pop("if_dest", None) or nested_vip.get("if_dest") or vip.get("if_dest") or ""),
        },
        hooks=hooks,
        options=deep_merge(config.get("migration") or {}, traffic_cfg),
    )


def probes_from_legacy_env(config: dict[str, Any]) -> list[ProbeSpec]:
    probes = [_probe_from_mapping(item) for item in _as_list(config.get("probes"))]
    postcopy = config.get("postcopy") or {}
    interval_ms = _optional_int(postcopy.get("readiness_interval_ms"))
    timeout_ms = _optional_int(postcopy.get("readiness_timeout_ms"))
    for index, url in enumerate(_as_list(postcopy.get("readiness_urls")), start=1):
        probes.append(
            ProbeSpec(
                name=f"postcopy-readiness-{index}",
                type="http",
                target="destination",
                url=str(url),
                interval_ms=interval_ms,
                timeout_ms=timeout_ms,
                required=True,
                expected_status=200,
            )
        )
    for index, url in enumerate(_as_list(postcopy.get("warmup_urls")), start=1):
        probes.append(
            ProbeSpec(
                name=f"postcopy-warmup-{index}",
                type="http",
                target="destination",
                url=str(url),
                interval_ms=_optional_int(postcopy.get("warmup_interval_ms")),
                timeout_ms=_optional_int(postcopy.get("warmup_max_duration_ms")),
                required=False,
                expected_status=200,
            )
        )
    return probes


def _probe_from_mapping(value: Any) -> ProbeSpec:
    from clm.monitoring.probes import parse_probe_spec

    return parse_probe_spec(value).to_core_probe_spec()


def _strategy_from_method(method: Optional[str]) -> str:
    if not method:
        return "stop-and-copy"
    aliases = {
        "precopy": "pre-copy",
        "pre-copy": "pre-copy",
        "postcopy": "post-copy",
        "post-copy": "post-copy",
        "stop_and_copy": "stop-and-copy",
        "stop-and-copy": "stop-and-copy",
    }
    return aliases.get(str(method), str(method))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _as_list(value) if str(item))


def _command_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return _as_str_tuple(value)
