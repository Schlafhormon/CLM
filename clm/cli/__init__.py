"""Legacy CLI compatibility facade.

The large research-run orchestrator lives in :mod:`clm.cli.legacy_run`.
This package module intentionally stays small and keeps the historic
``clm.cli`` import and patch surface stable for callers and tests.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

from . import legacy_run as _legacy


def _legacy_names() -> tuple[str, ...]:
    return tuple(name for name in dir(_legacy) if not name.startswith("__"))


_LEGACY_NAMES = _legacy_names()
_ORIGINAL_FUNCTIONS: dict[str, Any] = {}
_ADAPTERS: dict[str, Any] = {}


def _sync_legacy_patch_points() -> None:
    """Mirror patched facade attributes into the legacy implementation."""

    namespace = globals()
    for name in _LEGACY_NAMES:
        if name not in namespace:
            continue
        current = namespace[name]
        if name in _ORIGINAL_FUNCTIONS and current is _ADAPTERS.get(name):
            current = _ORIGINAL_FUNCTIONS[name]
        setattr(_legacy, name, current)


def _sync_back_mutable_state() -> None:
    namespace = globals()
    for name in ("_ACTIVE_PROGRESS",):
        if hasattr(_legacy, name):
            namespace[name] = getattr(_legacy, name)


def _make_adapter(name: str):
    original = getattr(_legacy, name)

    @functools.wraps(original)
    def adapter(*args, **kwargs):
        _sync_legacy_patch_points()
        try:
            return original(*args, **kwargs)
        finally:
            _sync_back_mutable_state()

    return adapter


for _name in _LEGACY_NAMES:
    _value = getattr(_legacy, _name)
    if inspect.isfunction(_value) and getattr(_value, "__module__", None) == _legacy.__name__:
        _adapter = _make_adapter(_name)
        _ORIGINAL_FUNCTIONS[_name] = _value
        _ADAPTERS[_name] = _adapter
        globals()[_name] = _adapter
    else:
        globals()[_name] = _value


__all__ = tuple(name for name in _LEGACY_NAMES if name != "_legacy")
