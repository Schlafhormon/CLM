"""Shared filesystem storage backend."""

from __future__ import annotations

from typing import Any

from clm.core.models import StoragePlan
from clm.migration.storage.base import ArtifactPaths, StorageBackend, TransferPlan, path_join


DEFAULT_SHARE_ROOT = "/mnt/criu"
DEFAULT_DESTINATION_ROOT = "/var/lib/criu-local"


class SharedFilesystemBackend(StorageBackend):
    """Adapter for the current shared `/mnt/criu` checkpoint layout."""

    name = "shared"

    def __init__(self, plan: StoragePlan | None = None):
        super().__init__(plan or StoragePlan(mode=self.name))

    def transfer_plan(self, config: dict[str, Any], *, method: str, run_id: str) -> TransferPlan:
        paths = config.get("paths") or {}
        precopy = config.get("precopy") or {}
        storage = config.get("storage") or {}

        share_root = str(storage.get("share_root") or paths.get("share_root") or self.plan.share_root or DEFAULT_SHARE_ROOT)
        destination_root = str(
            storage.get("destination_root")
            or storage.get("dst_local_root")
            or self.plan.options.get("destination_root")
            or self.plan.options.get("dst_local_root")
            or DEFAULT_DESTINATION_ROOT
        )
        image_mode = str(storage.get("image_mode") or precopy.get("image_mode") or self.plan.image_mode or "shared")
        if method == "postcopy":
            # The current post-copy script always copies images into the
            # destination-local lazy-pages cache before restore.
            image_mode = "local_copy"

        return TransferPlan(
            mode="shared",
            implemented=True,
            source_root=share_root,
            remote_root=str(storage.get("remote_share_root") or storage.get("remote_root") or share_root),
            destination_root=destination_root,
            precopy_image_mode=image_mode,
            restore_from_shared=(method == "precopy" and image_mode == "shared"),
            env={
                "SRC_NFS_ROOT": share_root,
                "REMOTE_NFS_ROOT": str(storage.get("remote_share_root") or storage.get("remote_root") or share_root),
                "DST_LOCAL_ROOT": destination_root,
                "PRECOPY_IMAGE_MODE": image_mode,
            },
            notes={"current_legacy_path": share_root},
        )

    def artifact_paths(self, config: dict[str, Any], *, method: str, run_id: str) -> ArtifactPaths:
        from clm.cli import checkpoint_name_for_run

        cp_name = checkpoint_name_for_run(method, run_id)
        container_name = str((config.get("container") or {}).get("name") or "testweb")
        transfer = self.transfer_plan(config, method=method, run_id=run_id)
        shared_container = path_join(transfer.source_root, "runc", container_name)
        destination_container = path_join(transfer.destination_root, "runc", container_name)
        return ArtifactPaths(
            checkpoint_name=cp_name,
            shared_checkpoint_path=path_join(shared_container, cp_name),
            destination_checkpoint_path=path_join(destination_container, cp_name),
            shared_container_path=shared_container,
            destination_container_path=destination_container,
        )

