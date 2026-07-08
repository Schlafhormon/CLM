"""Post-copy migration strategy."""

from __future__ import annotations

from clm.migration.strategies.legacy import LegacyAdapterStrategy


class PostCopyStrategy(LegacyAdapterStrategy):
    """Post-copy strategy skeleton backed by the legacy runc adapter."""

    def __init__(self) -> None:
        super().__init__(name="post-copy", legacy_method="postcopy")

