"""Cleanup policy model for migration artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SAFE_CLEANUP_ACTIONS = frozenset(
    {
        "shared_checkpoint_artifacts",
        "destination_checkpoint_artifacts",
        "run_temp_files",
    }
)
RISKY_CLEANUP_ACTIONS = frozenset(
    {
        "source_container_state",
        "destination_container_state",
        "network_state",
        "shared_container_directory",
        "destination_container_directory",
    }
)


@dataclass(frozen=True)
class CleanupPolicy:
    """Decide which cleanup actions are allowed for a run."""

    shared_images_policy: str = "success_only"
    local_images_policy: str = "success_only"
    risky_actions_enabled: bool = False
    explicit_risky_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "shared_images_policy", normalize_policy(self.shared_images_policy))
        object.__setattr__(self, "local_images_policy", normalize_policy(self.local_images_policy))
        object.__setattr__(
            self,
            "explicit_risky_actions",
            tuple(str(action) for action in (self.explicit_risky_actions or ())),
        )

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "CleanupPolicy":
        cfg = dict((config or {}).get("cleanup") or config or {})
        explicit = cfg.get("explicit_risky_actions", cfg.get("risky_actions", ()))
        if isinstance(explicit, str):
            explicit = [item.strip() for item in explicit.split(",") if item.strip()]
        return cls(
            shared_images_policy=cfg.get("shared_images_policy", "success_only"),
            local_images_policy=cfg.get("local_images_policy", "success_only"),
            risky_actions_enabled=as_bool(cfg.get("risky_actions_enabled", cfg.get("allow_risky", False))),
            explicit_risky_actions=tuple(explicit or ()),
        )

    def allows_artifact_cleanup(self, location: str, *, run_ok: bool) -> bool:
        """Return whether safe checkpoint artifacts may be removed."""

        policy = self.shared_images_policy if location == "shared" else self.local_images_policy
        return policy_allows_cleanup(policy, run_ok=run_ok)

    def allows_risky_action(self, action: str) -> bool:
        """Risky cleanup is opt-in per action or by explicit global switch."""

        normalized = str(action or "").strip()
        if normalized in SAFE_CLEANUP_ACTIONS:
            return True
        if normalized not in RISKY_CLEANUP_ACTIONS:
            return False
        return self.risky_actions_enabled or normalized in set(self.explicit_risky_actions)

    def describe(self) -> dict[str, Any]:
        return {
            "shared_images_policy": self.shared_images_policy,
            "local_images_policy": self.local_images_policy,
            "risky_actions_enabled": self.risky_actions_enabled,
            "explicit_risky_actions": list(self.explicit_risky_actions),
        }


def normalize_policy(policy: str | None) -> str:
    value = str(policy or "success_only").strip().lower().replace("-", "_")
    if value in {"on_success", "success"}:
        return "success_only"
    if value in {"always", "success_only", "never"}:
        return value
    return "never"


def policy_allows_cleanup(policy: str, *, run_ok: bool) -> bool:
    mode = normalize_policy(policy)
    if mode == "always":
        return True
    if mode == "success_only":
        return bool(run_ok)
    return False


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

