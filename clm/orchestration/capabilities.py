"""Capability gates shared by run and preflight commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clm.core.config import legacy_env_to_migration_request
from clm.core.models import PreflightResult
from clm.migration.storage import select_storage_backend
from clm.migration.strategies import LegacyAdapterStrategy, canonical_strategy_name, select_strategy
from clm.migration.traffic import select_traffic_backend
from clm.runtimes import select_backend


def validate_run_capabilities(cfg: dict[str, Any], method: str) -> PreflightResult:
    """Validate capabilities required by the legacy ``clm run`` path.

    The gate is intentionally side-effect free. It selects configured runtime,
    strategy, storage, traffic, and CRIU settings, but does not contact remote
    hosts or inspect NFS/tooling state.
    """

    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []
    metadata: dict[str, Any] = {"method": method}
    request = None
    strategy = None
    backend = None

    try:
        requested_strategy = canonical_strategy_name(method)
        checks.append({"name": "strategy: requested", "ok": True, "detail": requested_strategy})
        metadata["strategy"] = requested_strategy
    except Exception as exc:
        checks.append({"name": "strategy: requested", "ok": False, "detail": str(exc)})
        blockers.append(str(exc))

    configured_strategy = (cfg.get("migration") or {}).get("strategy") or cfg.get("strategy")
    if configured_strategy not in (None, ""):
        try:
            configured_canonical = canonical_strategy_name(configured_strategy)
            checks.append({"name": "strategy: configured", "ok": True, "detail": configured_canonical})
            metadata["configured_strategy"] = configured_canonical
        except Exception as exc:
            checks.append({"name": "strategy: configured", "ok": False, "detail": str(exc)})
            blockers.append(str(exc))

    try:
        request = legacy_env_to_migration_request(cfg, method=method)
        metadata["runtime"] = request.runtime.type
        metadata["criu_binary"] = request.criu.binary
    except Exception as exc:
        checks.append({"name": "config: migration request", "ok": False, "detail": str(exc)})
        blockers.append(f"Invalid migration config: {exc}")

    try:
        strategy = select_strategy(cfg, requested=method)
        checks.append({"name": "strategy: selected", "ok": True, "detail": strategy.name})
        if not isinstance(strategy, LegacyAdapterStrategy) or strategy.legacy_method not in ("precopy", "postcopy"):
            blockers.append(f"Migration strategy '{strategy.name}' is not implemented for clm run")
    except Exception as exc:
        checks.append({"name": "strategy: selected", "ok": False, "detail": str(exc)})
        blockers.append(str(exc))

    try:
        backend = select_backend(cfg)
        checks.append({"name": "runtime: selected", "ok": True, "detail": backend.runtime.type})
        if not bool(getattr(backend, "migration_supported", False)):
            blockers.append(
                f"Runtime '{backend.runtime.type}' migration is not implemented for clm run; "
                "supported runtime is rootful runc"
            )
    except Exception as exc:
        checks.append({"name": "runtime: selected", "ok": False, "detail": str(exc)})
        blockers.append(str(exc))

    if request is not None:
        runtime = request.runtime
        privilege_mode = str(runtime.privilege_mode or "").strip().lower()
        if runtime.rootless or privilege_mode == "rootless":
            blockers.append(
                f"Rootless runtime migration is not supported by clm run "
                f"(runtime={runtime.type}, privilege_mode={runtime.privilege_mode})"
            )

        criu_binary = str(request.criu.binary or "criu").strip()
        criu_name = Path(criu_binary).name
        if criu_name != "criu":
            blockers.append(
                f"Configured CRIU binary '{criu_binary}' is not supported by clm run; "
                "legacy runc scripts call 'criu'"
            )
        if request.criu.custom_build:
            blockers.append(
                f"Configured CRIU custom_build '{request.criu.custom_build}' is not supported by clm run; "
                "legacy runc scripts do not select custom CRIU builds"
            )

    if strategy is not None and backend is not None:
        try:
            strategy_result = strategy.preflight(cfg)
            checks.extend(strategy_result.checks)
            warnings.extend(strategy_result.warnings)
            blockers.extend(strategy_result.blockers)
            metadata.update(strategy_result.metadata)
        except Exception as exc:
            checks.append({"name": "strategy: preflight", "ok": False, "detail": str(exc)})
            blockers.append(str(exc))

    try:
        storage = select_storage_backend(cfg)
        checks.append({"name": "storage: selected", "ok": True, "detail": storage.plan.mode})
        transfer = storage.transfer_plan(cfg, method=_legacy_method_for_transfer(strategy, method), run_id="preflight")
        checks.append(
            {
                "name": "storage: transfer plan",
                "ok": bool(transfer.implemented),
                "detail": transfer.mode,
            }
        )
        warnings.extend(str(warning) for warning in transfer.warnings)
        if not transfer.implemented:
            message = transfer.warnings[0] if transfer.warnings else f"Storage mode '{transfer.mode}' is not implemented for clm run"
            blockers.append(str(message))
    except Exception as exc:
        checks.append({"name": "storage: selected", "ok": False, "detail": str(exc)})
        blockers.append(str(exc))

    try:
        traffic_result = select_traffic_backend(cfg).preflight(cfg)
        checks.extend(traffic_result.checks)
        warnings.extend(traffic_result.warnings)
        blockers.extend(traffic_result.blockers)
        if traffic_result.metadata:
            metadata["traffic"] = traffic_result.metadata
    except Exception as exc:
        checks.append({"name": "traffic: selected", "ok": False, "detail": str(exc)})
        blockers.append(str(exc))

    return PreflightResult(
        checks=tuple(checks),
        warnings=tuple(str(w) for w in warnings),
        blockers=tuple(_dedupe(blockers)),
        metadata=metadata,
    )


def method_for_preflight(cfg: dict[str, Any]) -> str:
    """Resolve the method a legacy preflight should gate by default."""

    migration = cfg.get("migration") or {}
    return str(
        migration.get("method")
        or migration.get("strategy")
        or cfg.get("method")
        or cfg.get("strategy")
        or "precopy"
    )


def _legacy_method_for_transfer(strategy: Any, method: str) -> str:
    legacy_method = getattr(strategy, "legacy_method", None)
    if legacy_method in ("precopy", "postcopy"):
        return legacy_method
    try:
        canonical = canonical_strategy_name(method)
    except Exception:
        return method
    if canonical == "post-copy":
        return "postcopy"
    return "precopy"


def _dedupe(values: list[Any]) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in out:
            out.append(text)
    return tuple(out)
