"""Analysis package boundaries.

Core code should depend on :mod:`clm.analysis.summary`. Batch ingestion,
statistics, and plotting remain available through :mod:`clm.analysis.advanced`
as optional analysis functionality.
"""

from clm.analysis.summary import CoreSummary, build_core_summary, summarize_run_dir

__all__ = ["CoreSummary", "build_core_summary", "summarize_run_dir"]
