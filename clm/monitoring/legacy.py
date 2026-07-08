"""Adapters for the existing tools/monitor/monitor.py artifacts.

The current monitor remains the runtime implementation for now. This module is
the compatibility boundary: it parses legacy CSV logs into the stable
monitoring result structures used by new code.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from clm.monitoring.events import ProbeResult
from clm.monitoring.probes import ProbeSpec


CORE_MONITORING_FEATURES = (
    "http_probes",
    "tcp_probes",
    "command_app_readiness",
    "downtime_windows",
    "migration_timeline",
    "probe_event_stream",
)

LEGACY_OPTIONAL_MONITORING_FEATURES = (
    "info_targets",
    "counter_targets",
    "stream_targets",
    "download_targets",
    "upload_targets",
    "research_batch_analysis",
    "paper_plots",
)


def load_legacy_probe_results(base_out: str | Path) -> tuple[ProbeResult, ...]:
    """Load HTTP and TCP probe results from the legacy monitor file prefix."""

    base = Path(base_out)
    return (
        *parse_legacy_http_csv(base.with_name(base.name + "-http.csv")),
        *parse_legacy_l4_csv(base.with_name(base.name + "-l4.csv")),
    )


def parse_legacy_http_csv(path: str | Path) -> tuple[ProbeResult, ...]:
    """Parse legacy `mon-http.csv` records into stable HTTP ProbeResult values."""

    p = Path(path)
    if not p.exists():
        return ()

    results = []
    for row in _csv_dict_rows(p):
        target = str(row.get("target") or "http")
        status_code = _optional_int(row.get("status"))
        ts_ms = _optional_int(row.get("t_end_ms")) or _optional_int(row.get("ts_ms"))
        if ts_ms is None:
            continue
        error = str(row.get("err") or "").strip() or None
        spec = ProbeSpec.http(name=target, url=str(row.get("url") or f"http://legacy.invalid/{target}"))
        results.append(
            ProbeResult(
                probe=spec,
                status="success" if status_code == 200 else "failure",
                timestamp_ms=ts_ms,
                duration_ms=_optional_float(row.get("rt_ms")),
                http_status=status_code,
                error=error,
                metadata={"legacy_target": target, "ts_iso": row.get("ts_iso")},
            )
        )
    return tuple(results)


def parse_legacy_l4_csv(path: str | Path) -> tuple[ProbeResult, ...]:
    """Parse legacy `mon-l4.csv` records into stable TCP ProbeResult values."""

    p = Path(path)
    if not p.exists():
        return ()

    results = []
    for row in _csv_dict_rows(p):
        target = str(row.get("target") or "tcp")
        state = str(row.get("state") or "").strip().lower()
        ts_ms = _optional_int(row.get("t_end_ms")) or _optional_int(row.get("ts_ms"))
        port = _optional_int(row.get("port")) or 1
        host = str(row.get("host") or target)
        if ts_ms is None or state not in {"up", "down"}:
            continue
        spec = ProbeSpec.tcp(name=target, host=host, port=port)
        results.append(
            ProbeResult(
                probe=spec,
                status="success" if state == "up" else "failure",
                timestamp_ms=ts_ms,
                metadata={"legacy_target": target, "legacy_state": state, "ts_iso": row.get("ts_iso")},
            )
        )
    return tuple(results)


def _csv_dict_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fp:
        sample = fp.readline()
        fp.seek(0)
        if sample.startswith("ts_"):
            return [dict(row) for row in csv.DictReader(fp)]
        reader = csv.reader(fp)
        return [_legacy_row_to_dict(row, path.name) for row in reader if row]


def _legacy_row_to_dict(row: list[str], filename: str) -> dict[str, Any]:
    if "-l4" in filename:
        fields = ("ts_iso", "ts_ms", "target", "host", "port", "state", "t_start_ms", "t_end_ms")
    else:
        fields = (
            "ts_iso",
            "ts_ms",
            "target",
            "status",
            "rt_ms",
            "ttfb_ms",
            "headers_ms",
            "dns_ms",
            "tcp_ms",
            "tls_ms",
            "bytes",
            "err",
            "t_start_ms",
            "t_end_ms",
        )
    return {field: row[idx] if idx < len(row) else None for idx, field in enumerate(fields)}


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
