"""Rsync transfer backend skeleton."""

from __future__ import annotations

from typing import Any

from clm.core.models import StoragePlan
from clm.migration.storage.base import ArtifactPaths, StorageBackend, TransferPlan, path_join
from clm.migration.storage.shared import DEFAULT_DESTINATION_ROOT, DEFAULT_SHARE_ROOT


class RsyncTransferBackend(StorageBackend):
    """Plan rsync-based transfer without changing the legacy migration path yet."""

    name = "rsync"

    def __init__(self, plan: StoragePlan | None = None):
        super().__init__(plan or StoragePlan(mode=self.name))

    def transfer_plan(self, config: dict[str, Any], *, method: str, run_id: str) -> TransferPlan:
        paths = config.get("paths") or {}
        storage = config.get("storage") or {}
        source_root = str(storage.get("source_root") or storage.get("share_root") or paths.get("share_root") or DEFAULT_SHARE_ROOT)
        destination_root = str(
            storage.get("destination_root")
            or storage.get("dst_local_root")
            or self.plan.options.get("destination_root")
            or self.plan.options.get("dst_local_root")
            or DEFAULT_DESTINATION_ROOT
        )
        return TransferPlan(
            mode="rsync",
            implemented=False,
            source_root=source_root,
            remote_root=str(storage.get("remote_root") or source_root),
            destination_root=destination_root,
            precopy_image_mode="rsync",
            restore_from_shared=False,
            env={
                "SRC_NFS_ROOT": source_root,
                "REMOTE_NFS_ROOT": str(storage.get("remote_root") or source_root),
                "DST_LOCAL_ROOT": destination_root,
                "PRECOPY_IMAGE_MODE": "rsync",
            },
            warnings=(
                "rsync transfer is modeled for planning/preflight, but the legacy migration scripts do not execute it yet.",
            ),
            notes={"requires": ("rsync", "ssh")},
        )

    def artifact_paths(self, config: dict[str, Any], *, method: str, run_id: str) -> ArtifactPaths:
        from clm.cli import checkpoint_name_for_run

        cp_name = checkpoint_name_for_run(method, run_id)
        container_name = str((config.get("container") or {}).get("name") or "testweb")
        transfer = self.transfer_plan(config, method=method, run_id=run_id)
        source_container = path_join(transfer.source_root, "runc", container_name)
        destination_container = path_join(transfer.destination_root, "runc", container_name)
        return ArtifactPaths(
            checkpoint_name=cp_name,
            shared_checkpoint_path=path_join(source_container, cp_name),
            destination_checkpoint_path=path_join(destination_container, cp_name),
            shared_container_path=source_container,
            destination_container_path=destination_container,
        )

