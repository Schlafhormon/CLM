"""Core migration summary helpers.

This module intentionally avoids pandas, numpy, matplotlib, and batch-analysis
dependencies. It extracts the operator-facing fields that belong in the CLM
core path: status, duration, downtime, errors, and artifact paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


SUMMARY_SCHEMA_VERSION = "clm.analysis.summary.v1"

_DURATION_KEYS = (
    "duration_ms",
    "migration_duration_ms",
    "total_duration_ms",
    "elapsed_ms",
)

_DOWNTIME_KEYS = (
    "http_downtime_ms",
    "l4_downtime_ms",
    "downtime_ms",
    "vip_http_client_visible_total_down_ms",
    "vip_http_downtime_ms",
    "vip_l4_downtime_ms",
)

_ARTIFACT_CANDIDATES = {
    "summary": ("summary.json", "monitor/summary.json"),
    "status": ("status.json", "meta/run.json"),
    "events": ("events.ndjson", "monitor/events.ndjson"),
    "monitor": ("monitor",),
    "analysis": ("analysis",),
}


@dataclass(frozen=True)
class CoreSummary:
    """Small, stable summary for the core migration path."""

    status: str
    duration_ms: Optional[float] = None
    downtime_ms: Optional[float] = None
    downtime: dict[str, Optional[float]] = field(default_factory=dict)
    errors: tuple[str, ...] = field(default_factory=tuple)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    source: Optional[str] = None
    schema_version: str = SUMMARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", normalize_status(self.status))
        object.__setattr__(self, "errors", tuple(str(item) for item in (self.errors or ()) if str(item)))
        object.__setattr__(self, "downtime", dict(self.downtime or {}))
        object.__setattr__(self, "artifact_paths", {str(k): str(v) for k, v in (self.artifact_paths or {}).items()})

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "success", "succeeded"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_version,
            "status": self.status,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "downtime_ms": self.downtime_ms,
            "downtime": dict(self.downtime),
            "errors": list(self.errors),
            "artifact_paths": dict(self.artifact_paths),
            "source": self.source,
        }


def build_core_summary(
    data: Mapping[str, Any] | Any | None = None,
    *,
    run_dir: str | Path | None = None,
    artifact_paths: Mapping[str, str | Path] | None = None,
    source: str | None = None,
) -> CoreSummary:
    """Build a core summary from a mapping or a core MigrationResult-like object."""

    payload = _mapping_from_any(data)
    paths = _artifact_paths_from_payload(payload)
    paths.update({str(k): str(v) for k, v in (artifact_paths or {}).items() if v is not None})
    if run_dir is not None:
        paths.update(_discover_artifact_paths(Path(run_dir)))

    status = normalize_status(payload.get("status") or ("error" if extract_errors(payload) else "unknown"))
    duration_ms = extract_duration_ms(payload)
    downtime = extract_downtime(payload)
    downtime_ms = _first_present(downtime.get(key) for key in _DOWNTIME_KEYS)

    return CoreSummary(
        status=status,
        duration_ms=duration_ms,
        downtime_ms=downtime_ms,
        downtime=downtime,
        errors=extract_errors(payload),
        artifact_paths=paths,
        source=source or _optional_str(payload.get("run_id") or payload.get("migration_id")),
    )


def summarize_run_dir(run_dir: str | Path) -> CoreSummary:
    """Load known run artifacts from a run directory and return a core summary."""

    root = Path(run_dir)
    payload: dict[str, Any] = {}
    status_path = _first_existing(root, _ARTIFACT_CANDIDATES["status"])
    summary_path = _first_existing(root, _ARTIFACT_CANDIDATES["summary"])
    if status_path is not None:
        payload.update(_read_json_object(status_path))
    if summary_path is not None:
        payload.update(_read_json_object(summary_path))
    return build_core_summary(payload, run_dir=root, source=str(root))


def normalize_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"ok", "success", "succeeded", "completed", "complete"}:
        return "ok"
    if text in {"fail", "failed", "failure", "error", "errored"}:
        return "failed"
    if text in {"running", "in_progress", "started"}:
        return "running"
    if text in {"aborted", "cancelled", "canceled"}:
        return "aborted"
    return text or "unknown"


def extract_duration_ms(data: Mapping[str, Any]) -> Optional[float]:
    for key in _DURATION_KEYS:
        value = _optional_float(data.get(key))
        if value is not None:
            return value

    timings = data.get("timings")
    if isinstance(timings, Mapping):
        for key in _DURATION_KEYS:
            value = _optional_float(timings.get(key))
            if value is not None:
                return value
        value = _optional_float(timings.get("duration_s"))
        if value is not None:
            return value * 1000.0

    start = _parse_datetime(data.get("started_at") or data.get("start_ts"))
    end = _parse_datetime(data.get("ended_at") or data.get("end_ts"))
    if start is not None and end is not None:
        return max(0.0, (end - start).total_seconds() * 1000.0)
    return None


def extract_downtime(data: Mapping[str, Any]) -> dict[str, Optional[float]]:
    downtime = {key: _optional_float(data.get(key)) for key in _DOWNTIME_KEYS if key in data}
    nested = data.get("downtime")
    if isinstance(nested, Mapping):
        for key, value in nested.items():
            downtime[str(key)] = _optional_float(value)
    return downtime


def extract_errors(data: Mapping[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for key in ("error", "message"):
        value = data.get(key)
        if value:
            out.append(str(value))
    value = data.get("errors")
    if isinstance(value, (list, tuple)):
        out.extend(str(item) for item in value if item)
    elif value:
        out.append(str(value))
    return tuple(dict.fromkeys(out))


def _mapping_from_any(data: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, Mapping):
        return dict(data)
    out: dict[str, Any] = {}
    for name in (
        "migration_id",
        "status",
        "started_at",
        "ended_at",
        "timings",
        "downtime_ms",
        "errors",
        "artifacts",
    ):
        if hasattr(data, name):
            out[name] = getattr(data, name)
    return out


def _artifact_paths_from_payload(data: Mapping[str, Any]) -> dict[str, str]:
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return {}
    return {str(key): str(value) for key, value in artifacts.items() if value is not None}


def _discover_artifact_paths(run_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, candidates in _ARTIFACT_CANDIDATES.items():
        path = _first_existing(run_dir, candidates)
        if path is not None:
            out[key] = str(path)
    return out


def _first_existing(root: Path, relative_candidates: tuple[str, ...]) -> Optional[Path]:
    for relative in relative_candidates:
        candidate = root / relative
        if candidate.exists():
            return candidate
    return None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _optional_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _first_present(values: Any) -> Optional[float]:
    for value in values:
        if value is not None:
            return value
    return None
