"""Storage and transfer backend interfaces."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional

from clm.core.models import StoragePlan


class StorageBackendError(RuntimeError):
    """Base error for storage backend failures."""


class UnsupportedStorageBackendError(StorageBackendError):
    """Raised when no storage backend exists for a storage mode."""


@dataclass(frozen=True)
class ArtifactPaths:
    """Run-specific checkpoint artifact locations."""

    checkpoint_name: str
    shared_checkpoint_path: str
    destination_checkpoint_path: str
    shared_container_path: str
    destination_container_path: str


@dataclass(frozen=True)
class TransferPlan:
    """How a checkpoint becomes visible to the destination runtime."""

    mode: str
    implemented: bool
    source_root: str
    remote_root: str
    destination_root: str
    precopy_image_mode: str
    restore_from_shared: bool
    env: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))


class StorageBackend(abc.ABC):
    """Interface implemented by storage/transfer adapters."""

    name: str

    def __init__(self, plan: Optional[StoragePlan] = None):
        self.plan = plan or StoragePlan(mode=self.name)

    @abc.abstractmethod
    def transfer_plan(self, config: dict[str, Any], *, method: str, run_id: str) -> TransferPlan:
        """Return script-compatible transfer settings for a migration run."""

    @abc.abstractmethod
    def artifact_paths(self, config: dict[str, Any], *, method: str, run_id: str) -> ArtifactPaths:
        """Return run-specific artifact paths."""


def normalize_storage_mode(mode: str | None) -> str:
    """Normalize storage mode names."""

    return str(mode or "shared").strip().lower().replace("-", "_")


def path_join(root: str, *parts: str) -> str:
    """Join POSIX-style paths used by remote Linux hosts."""

    base = str(root or "").rstrip("/")
    suffix = "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))
    if not suffix:
        return base or "/"
    return f"{base}/{suffix}" if base else f"/{suffix}"

