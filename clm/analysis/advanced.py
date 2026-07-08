"""Optional batch/statistics/plot analysis compatibility layer.

The implementation still lives in :mod:`clm.analysis_pipeline` for backwards
compatibility with existing imports. New code should import these heavier
batch- and plot-oriented helpers from this module so the optional boundary is
visible at call sites.
"""

from __future__ import annotations

from clm.analysis_pipeline import *  # noqa: F401,F403


ADVANCED_OPTIONAL_FEATURES = (
    "batch_run_ingest",
    "combined_batch_analysis",
    "summary_statistics",
    "bootstrap_confidence_intervals",
    "plot_generation",
    "paper_plot_configs",
    "probe_state_timeline_plots",
)


def is_advanced_optional_feature(name: str) -> bool:
    """Return whether a named analysis feature belongs to the optional layer."""

    return str(name or "").strip() in ADVANCED_OPTIONAL_FEATURES
