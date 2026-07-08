"""Legacy synthetic load profile helpers."""

from __future__ import annotations

from .legacy_run import (
    LEGACY_SYNTHETIC_LOAD_PROFILES,
    _load_target_urls,
    _spawn_load_loop,
    parse_load_modes,
    start_load,
    stop_load,
    validate_load_targets,
)

__all__ = (
    "LEGACY_SYNTHETIC_LOAD_PROFILES",
    "_load_target_urls",
    "_spawn_load_loop",
    "parse_load_modes",
    "start_load",
    "stop_load",
    "validate_load_targets",
)
