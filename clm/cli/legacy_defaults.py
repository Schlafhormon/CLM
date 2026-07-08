"""Legacy default configuration and config loading helpers."""

from __future__ import annotations

from clm.core.defaults import DEFAULTS

from .legacy_run import deep_merge, load_env, normalize_hosts

__all__ = ("DEFAULTS", "deep_merge", "load_env", "normalize_hosts")
