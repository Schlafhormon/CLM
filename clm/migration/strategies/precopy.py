"""Pre-copy migration strategy."""

from __future__ import annotations

from clm.migration.strategies.legacy import LegacyAdapterStrategy


class PreCopyStrategy(LegacyAdapterStrategy):
    """Pre-copy strategy skeleton backed by the legacy runc adapter."""

    def __init__(self) -> None:
        super().__init__(name="pre-copy", legacy_method="precopy")

