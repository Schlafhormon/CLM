"""Storage and transfer backend selection."""

from __future__ import annotations

from typing import Any

from clm.core.models import MigrationRequest, StoragePlan
from clm.migration.storage.base import (
    ArtifactPaths,
    StorageBackend,
    StorageBackendError,
    TransferPlan,
    UnsupportedStorageBackendError,
    normalize_storage_mode,
)
from clm.migration.storage.cleanup import CleanupPolicy, policy_allows_cleanup
from clm.migration.storage.rsync import RsyncTransferBackend
from clm.migration.storage.shared import SharedFilesystemBackend


_BACKENDS = {
    "shared": SharedFilesystemBackend,
    "shared_filesystem": SharedFilesystemBackend,
    "shared_fs": SharedFilesystemBackend,
    "nfs": SharedFilesystemBackend,
    "local_copy": SharedFilesystemBackend,
    "rsync": RsyncTransferBackend,
}


def storage_plan_from_config(config: dict[str, Any] | None) -> StoragePlan:
    """Derive a StoragePlan from the legacy config dictionary."""

    cfg = config or {}
    storage_cfg = dict(cfg.get("storage") or {})
    paths = cfg.get("paths") or {}
    precopy = cfg.get("precopy") or {}
    cleanup = cfg.get("cleanup") or {}
    image_mode = storage_cfg.pop("image_mode", None) or precopy.get("image_mode")
    mode = storage_cfg.pop("mode", None) or ("shared" if image_mode in (None, "shared", "local_copy") else str(image_mode))
    return StoragePlan(
        mode=str(mode),
        share_root=storage_cfg.pop("share_root", None) or paths.get("share_root"),
        runs_root=storage_cfg.pop("runs_root", None) or paths.get("runs_root"),
        logs_root=storage_cfg.pop("logs_root", None) or paths.get("logs_root"),
        image_mode=image_mode,
        cleanup_policy=dict(cleanup),
        options=storage_cfg,
    )


def select_storage_backend(source: dict[str, Any] | StoragePlan | MigrationRequest | None = None) -> StorageBackend:
    """Select a storage backend from config, StoragePlan, or MigrationRequest."""

    plan = _coerce_storage_plan(source)
    key = normalize_storage_mode(plan.mode)
    backend_cls = _BACKENDS.get(key)
    if backend_cls is None:
        raise UnsupportedStorageBackendError(f"Unsupported storage backend: {plan.mode}")
    return backend_cls(plan=plan)


def transfer_plan_for(source: dict[str, Any], *, method: str, run_id: str) -> TransferPlan:
    return select_storage_backend(source).transfer_plan(source, method=method, run_id=run_id)


def artifact_paths_for(source: dict[str, Any], *, method: str, run_id: str) -> ArtifactPaths:
    return select_storage_backend(source).artifact_paths(source, method=method, run_id=run_id)


def _coerce_storage_plan(source: dict[str, Any] | StoragePlan | MigrationRequest | None) -> StoragePlan:
    if source is None:
        return StoragePlan(mode="shared")
    if isinstance(source, StoragePlan):
        return source
    if isinstance(source, MigrationRequest):
        return source.storage
    if isinstance(source, dict):
        return storage_plan_from_config(source)
    raise TypeError(f"cannot select storage backend from {type(source).__name__}")


__all__ = [
    "ArtifactPaths",
    "CleanupPolicy",
    "RsyncTransferBackend",
    "SharedFilesystemBackend",
    "StorageBackend",
    "StorageBackendError",
    "TransferPlan",
    "UnsupportedStorageBackendError",
    "artifact_paths_for",
    "policy_allows_cleanup",
    "select_storage_backend",
    "storage_plan_from_config",
    "transfer_plan_for",
]
