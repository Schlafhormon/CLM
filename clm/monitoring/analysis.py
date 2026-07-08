"""Analysis helpers for legacy monitor artifacts.

This module contains the pure CSV/NDJSON summary logic that used to live in
tools/monitor/monitor.py. The runtime monitor still imports and re-exports these
names for CLI and private-helper compatibility.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
from collections import defaultdict

def _load_csv_rows(path, expected_headers=None):
    # Load CSV rows.
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)
    return rows

def _load_ndjson(path):
    # Load NDJSON.
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _parse_int_or_none(value):
    # Parse integer or none.
    try:
        return int(value)
    except Exception:
        return None

def _csv_to_dicts_http(rows):
    # Parse HTTP CSV records.
    dicts = []
    if not rows:
        return dicts

    has_header = rows[0] and isinstance(rows[0], list) and len(rows[0]) >= 4 and rows[0][0].startswith("ts_")
    start = 1 if has_header else 0
    for r in rows[start:]:
        try:
            status = None
            if r[3].isdigit():
                status = int(r[3])
            ts_raw = _parse_int_or_none(r[1])
            t_start_ms = _parse_int_or_none(r[12]) if len(r) > 12 else None
            t_end_ms = _parse_int_or_none(r[13]) if len(r) > 13 else None


            ts_effective = t_end_ms if t_end_ms is not None else ts_raw
            if ts_effective is None:
                continue
            d = {
                "ts_iso": r[0],
                "ts_ms": int(ts_effective),
                "ts_ms_raw": int(ts_raw) if ts_raw is not None else None,
                "t_start_ms": t_start_ms,
                "t_end_ms": t_end_ms,
                "target": r[2],
                "status": status,
                "rt_ms": float(r[4]) if r[4] else None,
                "ttfb_ms": float(r[5]) if r[5] else None,
                "headers_ms": float(r[6]) if r[6] else None,
                "dns_ms": float(r[7]) if r[7] else None,
                "tcp_ms": float(r[8]) if r[8] else None,
                "tls_ms": float(r[9]) if r[9] else None,
                "bytes": int(r[10]) if r[10] else None,
                "err": r[11] if len(r) > 11 else "",
            }
            dicts.append(d)
        except Exception:
            continue
    return dicts

def _csv_to_dicts_l4(rows):
    # Parse L4 CSV records.
    dicts = []
    if not rows:
        return dicts
    has_header = rows[0] and rows[0][0].startswith("ts_")
    start = 1 if has_header else 0
    for r in rows[start:]:
        try:
            state = r[5].strip().lower()
            if state not in ("up", "down"):
                continue
            ts_raw = _parse_int_or_none(r[1])
            t_start_ms = _parse_int_or_none(r[6]) if len(r) > 6 else None
            t_end_ms = _parse_int_or_none(r[7]) if len(r) > 7 else None
            ts_effective = t_end_ms if t_end_ms is not None else ts_raw
            if ts_effective is None:
                continue
            dicts.append({
                "ts_ms": int(ts_effective),
                "ts_ms_raw": int(ts_raw) if ts_raw is not None else None,
                "t_start_ms": t_start_ms,
                "t_end_ms": t_end_ms,
                "target": r[2],
                "state": state,
            })
        except Exception:
            continue
    return dicts


def _last_200_before(http_rows, target, t_ms):
    # Find the last HTTP success.
    ts = None
    for r in http_rows:
        r_ts = r.get("ts_ms")
        if r["target"] == target and r["status"] == 200 and isinstance(r_ts, int) and r_ts <= t_ms:
            ts = r["ts_ms"]
    return ts

def _first_200_after(http_rows, target, t_ms):
    # Find the first HTTP success.
    for r in http_rows:
        r_ts = r.get("ts_ms")
        if r["target"] == target and r["status"] == 200 and isinstance(r_ts, int) and r_ts >= t_ms:
            return r["ts_ms"]
    return None

def _first_up_after(l4_rows, target, t_ms):
    # Find the first L4 success.
    for r in l4_rows:
        r_ts = r.get("ts_ms")
        if r["target"] == target and r["state"] == "up" and isinstance(r_ts, int) and r_ts >= t_ms:
            return r["ts_ms"]
    return None

def _last_up_before(l4_rows, target, t_ms):
    # Find the last L4 success.
    ts = None
    for r in l4_rows:
        r_ts = r.get("ts_ms")
        if r["target"] == target and r["state"] == "up" and isinstance(r_ts, int) and r_ts <= t_ms:
            ts = r["ts_ms"]
    return ts

def _latency_stats(http_rows, target):
    # Compute latency statistics.
    vals = [r["rt_ms"] for r in http_rows if r["target"] == target and r["status"] == 200 and r["rt_ms"] is not None]
    if not vals:
        return {"p50_ms": None, "avg_ms": None}
    vals = sorted(vals)
    n = len(vals)
    p50 = vals[n//2] if n % 2 == 1 else (vals[n//2 - 1] + vals[n//2]) / 2.0
    avg = sum(vals) / n
    return {"p50_ms": round(p50, 3), "avg_ms": round(avg, 3)}

def _event_clock_domain(ev):
    # Resolve an event clock domain.
    raw = str((ev or {}).get("clock_domain") or (ev or {}).get("host_clock") or "").strip().lower()
    if raw in ("source", "dest", "monitor"):
        return raw
    name = str((ev or {}).get("event") or "").strip()

    if name in (
        "script_start",
        "pre_dump_round_start",
        "pre_dump_round_done",
        "final_dump_start",
        "final_dump_done",
        "transfer_start",
        "transfer_done",
        "checkpoint_start",
        "checkpoint_done",
        "vip_prepare_start",
        "vip_cutover_start",
        "vip_cutover_done",
        "health_ok",
        "script_done",
        "summary",
    ):
        return "source"
    return None


def _extract_clock_offsets(events):
    # Extract clock offsets.
    offsets = {"monitor": 0}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("event") != "clock_offset_estimate":
            continue
        host = str(ev.get("host") or "").strip().lower()
        if host not in ("source", "dest", "monitor"):
            continue
        off = _parse_int_or_none(ev.get("offset_ms"))
        if off is None:
            num = _safe_num(ev.get("offset_ms"))
            if num is None:
                continue
            off = int(round(num))
        offsets[host] = off
    return offsets


def _event_ts_in_monitor_clock(ev, clock_offsets):
    # Convert an event timestamp.
    raw_ts = _parse_int_or_none((ev or {}).get("ts_unix_ms") or (ev or {}).get("ts_ms"))
    if raw_ts is None:
        return None
    domain = _event_clock_domain(ev)
    if domain is None:
        return raw_ts
    off = (clock_offsets or {}).get(domain)
    if off is None:
        return raw_ts
    return int(raw_ts - int(off))


def _pick_cutover_event(events, clock_offsets):
    # Select cutover event.
    prefer = (
        "vip_cutover_start",
        "vip_cutover_done",
        "final_dump_start",
        "restore_start",
        "restore_done",
    )
    for name in prefer:
        for ev in events or []:
            if ev.get("event") != name:
                continue
            ts_raw = _parse_int_or_none(ev.get("ts_unix_ms") or ev.get("ts_ms"))
            if ts_raw is None:
                continue
            ts_corr = _event_ts_in_monitor_clock(ev, clock_offsets)
            return {
                "event": name,
                "ts_raw_ms": ts_raw,
                "ts_ms": ts_corr if ts_corr is not None else ts_raw,
                "clock_domain": _event_clock_domain(ev),
            }
    return None


def _first_event_ts(events, name, clock_offsets):
    # Find the first event timestamp.
    for ev in events or []:
        if ev.get("event") != name:
            continue
        ts = _event_ts_in_monitor_clock(ev, clock_offsets)
        if isinstance(ts, int):
            return ts
    return None


def _first_event_field(events, name, field):
    # Find the first event field.
    for ev in events or []:
        if ev.get("event") != name:
            continue
        value = ev.get(field)
        if value is not None:
            return value
    return None


def _first_event_field_int(events, name, field):
    # Parse the first event field.
    return _parse_int_or_none(_first_event_field(events, name, field))


def _first_event_ts_any(events, names, clock_offsets):
    # Find the first matching event.
    for name in names or []:
        ts = _first_event_ts(events, name, clock_offsets)
        if isinstance(ts, int):
            return ts
    return None


def _delta_ms(start_ms, end_ms):
    # Compute a positive duration.
    if not isinstance(start_ms, int) or not isinstance(end_ms, int):
        return None
    return int(end_ms - start_ms)


def _append_quality_flag(flags, flag):
    if not flag:
        return
    if flag not in flags:
        flags.append(str(flag))


def _infer_migration_method(markers):
    if not isinstance(markers, dict):
        return None
    if any(
        isinstance(markers.get(name), int)
        for name in (
            "dest_readiness_wait_start_ms_event",
            "dest_readiness_ok_ms_event",
            "postcopy_warmup_start_ms_event",
            "postcopy_warmup_done_ms_event",
            "postcopy_src_forward_start_ms_event",
            "checkpoint_start_ms_event",
            "checkpoint_done_ms_event",
        )
    ):
        return "postcopy"
    if any(
        isinstance(markers.get(name), int)
        for name in (
            "final_dump_start_ms_event",
            "final_dump_done_ms_event",
            "dest_container_cleanup_start_ms_event",
            "dest_container_cleanup_done_ms_event",
            "restore_exec_start_ms_event",
            "restore_exec_done_ms_event",
        )
    ):
        return "precopy"
    return None


def _phase_templates_for_method(method):
    m = str(method or "").strip().lower()
    if m == "precopy":
        return [
            {
                "phase_id": "final_dump",
                "label": "Final dump",
                "phase_group": "dump",
                "required": True,
                "alternatives": [("final_dump_start_ms_event", "final_dump_done_ms_event")],
            },
            {
                "phase_id": "transfer",
                "label": "Transfer",
                "phase_group": "transfer",
                "required": True,
                "alternatives": [("transfer_start_ms_event", "transfer_done_ms_event")],
            },
            {
                "phase_id": "restore",
                "label": "Restore",
                "phase_group": "restore",
                "required": True,
                "alternatives": [("restore_start_ms_event", "restore_done_ms_event")],
            },
            {
                "phase_id": "restore_to_cutover",
                "label": "Restore to cutover",
                "phase_group": "handoff",
                "required": True,
                "alternatives": [("restore_done_ms_event", "vip_cutover_start_ms_event")],
            },
            {
                "phase_id": "vip_cutover",
                "label": "VIP cutover",
                "phase_group": "cutover",
                "required": True,
                "alternatives": [("vip_cutover_start_ms_event", "vip_cutover_done_ms_event")],
            },
            {
                "phase_id": "health_wait",
                "label": "Health wait",
                "phase_group": "health",
                "required": True,
                "alternatives": [
                    ("health_wait_start_ms_event", "health_ok_ms_event"),
                    ("vip_cutover_done_ms_event", "health_ok_ms_event"),
                ],
            },
        ]
    if m == "postcopy":
        return [
            {
                "phase_id": "transfer",
                "label": "Transfer",
                "phase_group": "transfer",
                "required": True,
                "alternatives": [("transfer_start_ms_event", "transfer_done_ms_event")],
            },
            {
                "phase_id": "transfer_to_restore",
                "label": "Transfer to restore",
                "phase_group": "handoff",
                "required": True,
                "alternatives": [("transfer_done_ms_event", "restore_start_ms_event")],
            },
            {
                "phase_id": "restore",
                "label": "Restore",
                "phase_group": "restore",
                "required": True,
                "alternatives": [("restore_start_ms_event", "restore_done_ms_event")],
            },
            {
                "phase_id": "readiness_gate",
                "label": "Readiness gate",
                "phase_group": "readiness",
                "required": True,
                "alternatives": [("dest_readiness_wait_start_ms_event", "dest_readiness_ok_ms_event")],
            },
            {
                "phase_id": "warmup",
                "label": "Warmup",
                "phase_group": "warmup",
                "required": True,
                "alternatives": [("postcopy_warmup_start_ms_event", "postcopy_warmup_done_ms_event")],
            },
            {
                "phase_id": "warmup_to_cutover",
                "label": "Warmup to cutover",
                "phase_group": "handoff",
                "required": True,
                "alternatives": [
                    ("postcopy_warmup_done_ms_event", "vip_cutover_start_ms_event"),
                    ("dest_readiness_ok_ms_event", "vip_cutover_start_ms_event"),
                ],
            },
            {
                "phase_id": "vip_cutover",
                "label": "VIP cutover",
                "phase_group": "cutover",
                "required": True,
                "alternatives": [("vip_cutover_start_ms_event", "vip_cutover_done_ms_event")],
            },
            {
                "phase_id": "health_wait",
                "label": "Health wait",
                "phase_group": "health",
                "required": True,
                "alternatives": [
                    ("health_wait_start_ms_event", "health_ok_ms_event"),
                    ("vip_cutover_done_ms_event", "health_ok_ms_event"),
                ],
            },
        ]
    return []


def _resolve_phase_interval(markers, phase_spec, quality_flags):
    alternatives = list((phase_spec or {}).get("alternatives") or [])
    phase_id = str((phase_spec or {}).get("phase_id") or "phase")
    required = bool((phase_spec or {}).get("required", False))
    if not alternatives:
        return None

    for alt_idx, pair in enumerate(alternatives):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        marker_start, marker_end = pair
        start_ms = markers.get(marker_start)
        end_ms = markers.get(marker_end)
        if not isinstance(start_ms, int) or not isinstance(end_ms, int):
            continue
        if end_ms <= start_ms:
            _append_quality_flag(quality_flags, "non_monotonic_markers")
            continue
        status = "event" if alt_idx == 0 else "fallback"
        return {
            "phase_id": phase_id,
            "label": str((phase_spec or {}).get("label") or phase_id),
            "phase_group": str((phase_spec or {}).get("phase_group") or "other"),
            "start_ms": int(start_ms),
            "end_ms": int(end_ms),
            "marker_start": marker_start,
            "marker_end": marker_end,
            "status": status,
        }

    if required:
        primary_pair = alternatives[0]
        marker_start = primary_pair[0] if isinstance(primary_pair, (list, tuple)) and len(primary_pair) >= 1 else None
        marker_end = primary_pair[1] if isinstance(primary_pair, (list, tuple)) and len(primary_pair) >= 2 else None
        if marker_start and not isinstance(markers.get(marker_start), int):
            _append_quality_flag(quality_flags, f"missing_marker_{marker_start}")
        if marker_end and not isinstance(markers.get(marker_end), int):
            _append_quality_flag(quality_flags, f"missing_marker_{marker_end}")
        _append_quality_flag(quality_flags, f"phase_missing_{phase_id}")
    return None


def _make_unknown_segment(start_ms, end_ms, phase_id, label="Unknown / not explained by markers"):
    return {
        "phase_id": str(phase_id),
        "label": str(label),
        "phase_group": "unknown",
        "start_ms": int(start_ms),
        "end_ms": int(end_ms),
        "duration_ms": int(end_ms - start_ms),
        "status": "unknown",
        "marker_start": None,
        "marker_end": None,
    }


def _resolve_breakdown_basis(kind, method, markers, quality_flags):
    k = str(kind or "").strip().lower()
    m = str(method or "").strip().lower()

    if k == "client_visible_vip_http":
        observed_segments = markers.get("vip_http_client_visible_down_segments")
        if isinstance(observed_segments, list) and observed_segments:
            starts = [seg.get("start_ms") for seg in observed_segments if isinstance(seg, dict)]
            ends = [seg.get("end_ms") for seg in observed_segments if isinstance(seg, dict)]
            starts = [int(v) for v in starts if isinstance(v, int)]
            ends = [int(v) for v in ends if isinstance(v, int)]
            start_ms = min(starts) if starts else None
            end_ms = max(ends) if ends else None
            basis_metric = "vip_http_client_visible_total_down_ms"
        else:
            start_ms = markers.get("vip_http_segment_start_ms")
            end_ms = markers.get("vip_http_segment_end_ms")
            basis_metric = "vip_http_downtime_ms"
    elif k == "event_critical_path":
        basis_metric = None
        if m == "precopy":
            start_ms = markers.get("final_dump_start_ms_event")
            end_ms = markers.get("health_ok_ms_event")
        elif m == "postcopy":
            start_ms = markers.get("transfer_start_ms_event")
            if not isinstance(start_ms, int):
                start_ms = markers.get("restore_start_ms_event")
                if isinstance(start_ms, int):
                    _append_quality_flag(quality_flags, "basis_start_fallback_restore_start")
            end_ms = markers.get("health_ok_ms_event")
        else:
            start_ms = (
                markers.get("final_dump_start_ms_event")
                if isinstance(markers.get("final_dump_start_ms_event"), int)
                else markers.get("transfer_start_ms_event")
            )
            if not isinstance(start_ms, int):
                start_ms = markers.get("restore_start_ms_event")
            end_ms = markers.get("health_ok_ms_event")
            _append_quality_flag(quality_flags, "method_unknown")
    else:
        return None, None, None

    if not isinstance(start_ms, int) or not isinstance(end_ms, int):
        _append_quality_flag(quality_flags, "basis_missing")
        return None, None, basis_metric
    if end_ms <= start_ms:
        _append_quality_flag(quality_flags, "basis_non_monotonic")
        _append_quality_flag(quality_flags, "non_monotonic_markers")
        return None, None, basis_metric
    return int(start_ms), int(end_ms), basis_metric


def _build_breakdown_kind(kind, method, markers):
    quality_flags = []
    basis_start_ms, basis_end_ms, basis_metric = _resolve_breakdown_basis(kind, method, markers, quality_flags)
    breakdown = {
        "basis_start_ms": basis_start_ms,
        "basis_end_ms": basis_end_ms,
        "total_ms": (int(basis_end_ms - basis_start_ms) if isinstance(basis_start_ms, int) and isinstance(basis_end_ms, int) else None),
        "basis_metric": basis_metric,
        "method": str(method) if method else None,
        "segments": [],
        "quality_flags": quality_flags,
    }
    if not isinstance(basis_start_ms, int) or not isinstance(basis_end_ms, int):
        return breakdown

    if str(kind or "").strip().lower() == "client_visible_vip_http":
        observed_segments = markers.get("vip_http_client_visible_down_segments")
        if isinstance(observed_segments, list) and observed_segments:
            segments = []
            for idx, raw in enumerate(observed_segments, start=1):
                if not isinstance(raw, dict):
                    continue
                seg_start = raw.get("start_ms")
                seg_end = raw.get("end_ms")
                if not isinstance(seg_start, int) or not isinstance(seg_end, int) or seg_end <= seg_start:
                    continue
                seg = {
                    "phase_id": f"down_segment_{idx}",
                    "label": f"VIP HTTP down segment {idx}",
                    "phase_group": "http_down",
                    "start_ms": int(seg_start),
                    "end_ms": int(seg_end),
                    "duration_ms": int(seg_end - seg_start),
                    "status": "observed_down",
                    "marker_start": None,
                    "marker_end": None,
                    "phase_order": idx,
                }
                if raw.get("open_ended"):
                    seg["open_ended"] = True
                    _append_quality_flag(quality_flags, "open_ended_down_segment")
                if raw.get("clipped"):
                    seg["clipped"] = True
                    _append_quality_flag(quality_flags, "segment_clipped_to_migration_window")
                segments.append(seg)
            breakdown["segments"] = segments
            breakdown["total_ms"] = int(sum(seg["duration_ms"] for seg in segments))
            if len(segments) > 1:
                _append_quality_flag(quality_flags, "multiple_down_segments")
            return breakdown

    template = _phase_templates_for_method(method)
    if not template:
        _append_quality_flag(quality_flags, "method_unknown")
        breakdown["segments"] = [
            _make_unknown_segment(basis_start_ms, basis_end_ms, "unknown")
        ]
        breakdown["segments"][0]["phase_order"] = 1
        return breakdown

    candidates = []
    for phase_spec in template:
        resolved = _resolve_phase_interval(markers, phase_spec, quality_flags)
        if isinstance(resolved, dict):
            candidates.append(resolved)

    cursor = basis_start_ms
    have_real_phase = False
    phase_order = 1
    segments = []
    for segment in candidates:
        seg_start = max(int(segment["start_ms"]), basis_start_ms, cursor)
        seg_end = min(int(segment["end_ms"]), basis_end_ms)
        if seg_end <= seg_start:
            continue
        if seg_start > cursor:
            unknown_phase_id = "unknown_before_events" if not have_real_phase else "unknown_gap"
            unknown_seg = _make_unknown_segment(cursor, seg_start, unknown_phase_id)
            unknown_seg["phase_order"] = phase_order
            segments.append(unknown_seg)
            phase_order += 1
        clipped = dict(segment)
        clipped["start_ms"] = int(seg_start)
        clipped["end_ms"] = int(seg_end)
        clipped["duration_ms"] = int(seg_end - seg_start)
        clipped["phase_order"] = phase_order
        if seg_start != int(segment["start_ms"]) or seg_end != int(segment["end_ms"]):
            clipped["status"] = "clipped"
        segments.append(clipped)
        phase_order += 1
        cursor = int(seg_end)
        have_real_phase = True

    if cursor < basis_end_ms:
        if not have_real_phase:
            unknown_phase_id = "unknown"
        else:
            unknown_phase_id = "unknown_after_events"
        unknown_tail = _make_unknown_segment(cursor, basis_end_ms, unknown_phase_id)
        unknown_tail["phase_order"] = phase_order
        segments.append(unknown_tail)

    if any(str(seg.get("phase_group") or "") == "unknown" for seg in segments):
        _append_quality_flag(quality_flags, "unknown_present")
    breakdown["segments"] = segments
    return breakdown


def _build_downtime_breakdown(markers, method_hint=None):
    method = str(method_hint or "").strip().lower() or None
    if method not in ("precopy", "postcopy"):
        method = _infer_migration_method(markers)
    out = {"version": 1}
    for kind in ("client_visible_vip_http", "event_critical_path"):
        out[kind] = _build_breakdown_kind(kind, method, markers)
    return out


def _collect_down_segments(rows, target, is_down):
    # Collect downtime segments.
    segs = []
    cur_start = None
    last_down = None
    for r in rows:
        if r.get("target") != target:
            continue
        ts = r.get("ts_ms")
        if not isinstance(ts, int):
            continue
        down = bool(is_down(r))
        if down:
            if cur_start is None:
                cur_start = ts
            last_down = ts
            continue
        if cur_start is not None:
            end_ms = ts if isinstance(ts, int) else last_down
            if isinstance(end_ms, int) and end_ms >= cur_start:
                segs.append(
                    {
                        "start_ms": int(cur_start),
                        "end_ms": int(end_ms),
                        "duration_ms": int(end_ms - cur_start),
                        "open_ended": False,
                    }
                )
            cur_start = None
            last_down = None
    if cur_start is not None and isinstance(last_down, int) and last_down >= cur_start:
        segs.append(
            {
                "start_ms": int(cur_start),
                "end_ms": int(last_down),
                "duration_ms": int(last_down - cur_start),
                "open_ended": True,
            }
        )
    return segs


def _segment_distance_to_ts(seg, ts_ms):
    # Measure distance to a segment.
    start = seg.get("start_ms")
    end = seg.get("end_ms")
    if not isinstance(start, int) or not isinstance(end, int) or not isinstance(ts_ms, int):
        return None
    if start <= ts_ms <= end:
        return 0
    if ts_ms < start:
        return start - ts_ms
    return ts_ms - end


def _select_client_visible_segment(segments, cutover_ms, tolerance_ms=0):
    # Select client visible segment.
    if not segments:
        return None
    if isinstance(cutover_ms, int):
        tol = max(0, int(tolerance_ms or 0))
        scored = []
        for s in segments:
            dist = _segment_distance_to_ts(s, cutover_ms)
            if not isinstance(dist, int):
                continue
            duration = int(s.get("duration_ms", 0) or 0)
            eff_dist = max(0, int(dist) - tol)


            scored.append((eff_dist, -duration, int(dist), int(s.get("start_ms", 0) or 0), s))
        if scored:
            scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
            return scored[0][4]
    return max(segments, key=lambda s: s.get("duration_ms", -1))


def _migration_relevant_vip_http_window(
    method,
    *,
    final_dump_start_ms=None,
    checkpoint_start_ms=None,
    transfer_start_ms=None,
    restore_start_ms=None,
    health_ok_ms=None,
    cutover_ms=None,
    http_rows=None,
    fallback_window_ms=10_000,
):
    # Find the relevant VIP HTTP window.
    rows = list(http_rows or [])
    quality_flags = []
    m = str(method or "").strip().lower()
    if m == "postcopy":
        start_ms = checkpoint_start_ms if isinstance(checkpoint_start_ms, int) else restore_start_ms
        if not isinstance(start_ms, int):
            start_ms = transfer_start_ms
            if isinstance(start_ms, int):
                _append_quality_flag(quality_flags, "client_window_start_fallback_transfer_start")
    elif m == "precopy":
        start_ms = final_dump_start_ms if isinstance(final_dump_start_ms, int) else checkpoint_start_ms
        if not isinstance(start_ms, int):
            for candidate_name, candidate in (
                ("transfer_start", transfer_start_ms),
                ("restore_start", restore_start_ms),
            ):
                if isinstance(candidate, int):
                    start_ms = candidate
                    _append_quality_flag(quality_flags, f"client_window_start_fallback_{candidate_name}")
                    break
    else:
        start_ms = final_dump_start_ms if isinstance(final_dump_start_ms, int) else checkpoint_start_ms
        if not isinstance(start_ms, int):
            start_ms = restore_start_ms if isinstance(restore_start_ms, int) else transfer_start_ms
        _append_quality_flag(quality_flags, "client_window_method_unknown")

    if not isinstance(start_ms, int):
        if isinstance(cutover_ms, int):
            start_ms = int(cutover_ms - int(fallback_window_ms))
            _append_quality_flag(quality_flags, "client_window_start_fallback_cutover_window")
        else:
            starts = [r.get("ts_ms") for r in rows if r.get("target") == "vip" and isinstance(r.get("ts_ms"), int)]
            start_ms = min(starts) if starts else None
            _append_quality_flag(quality_flags, "client_window_start_fallback_monitor_min")

    if isinstance(health_ok_ms, int):
        first_healthy_after = _first_200_after(rows, "vip", health_ok_ms)
        end_ms = max(health_ok_ms, first_healthy_after) if isinstance(first_healthy_after, int) else health_ok_ms
    elif isinstance(cutover_ms, int):
        first_healthy_after = _first_200_after(rows, "vip", cutover_ms)
        end_ms = first_healthy_after if isinstance(first_healthy_after, int) else int(cutover_ms + int(fallback_window_ms))
        _append_quality_flag(quality_flags, "client_window_end_fallback_cutover_recovery")
    else:
        ends = [r.get("ts_ms") for r in rows if r.get("target") == "vip" and isinstance(r.get("ts_ms"), int)]
        end_ms = max(ends) if ends else None
        _append_quality_flag(quality_flags, "client_window_end_fallback_monitor_max")

    if isinstance(start_ms, int) and isinstance(end_ms, int) and end_ms <= start_ms:
        _append_quality_flag(quality_flags, "client_window_non_monotonic")
        if isinstance(cutover_ms, int):
            start_ms = int(cutover_ms - int(fallback_window_ms))
            end_ms = int(cutover_ms + int(fallback_window_ms))
            _append_quality_flag(quality_flags, "client_window_fallback_cutover_window")
    return start_ms, end_ms, quality_flags


def _clip_down_segments_to_window(segments, window_start_ms, window_end_ms):
    # Clip downtime segments.
    if not isinstance(window_start_ms, int) or not isinstance(window_end_ms, int) or window_end_ms <= window_start_ms:
        return []
    out = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        start = seg.get("start_ms")
        end = seg.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        clipped_start = max(int(start), int(window_start_ms))
        clipped_end = min(int(end), int(window_end_ms))
        if clipped_end <= clipped_start:
            continue
        item = dict(seg)
        item["start_ms"] = int(clipped_start)
        item["end_ms"] = int(clipped_end)
        item["duration_ms"] = int(clipped_end - clipped_start)
        if clipped_start != int(start) or clipped_end != int(end):
            item["clipped"] = True
        out.append(item)
    out.sort(key=lambda s: (int(s.get("start_ms", 0) or 0), int(s.get("end_ms", 0) or 0)))
    return out


def _client_visible_down_metrics(segments):
    # Compute client-visible downtime.
    clean = [seg for seg in (segments or []) if isinstance(seg, dict) and isinstance(seg.get("start_ms"), int) and isinstance(seg.get("end_ms"), int) and seg.get("end_ms") > seg.get("start_ms")]
    if not clean:
        return {
            "total_down_ms": 0,
            "down_segments": 0,
            "outage_span_ms": 0,
            "first_down_ms": None,
            "final_recovery_ms": None,
        }
    first_down = min(int(seg["start_ms"]) for seg in clean)
    final_recovery = max(int(seg["end_ms"]) for seg in clean)
    return {
        "total_down_ms": int(sum(int(seg["end_ms"]) - int(seg["start_ms"]) for seg in clean)),
        "down_segments": int(len(clean)),
        "outage_span_ms": int(final_recovery - first_down),
        "first_down_ms": int(first_down),
        "final_recovery_ms": int(final_recovery),
    }

def _heuristic_cutover_from_http(http_rows):
    # Infer cutover from HTTP samples.

    t_src_last = _last_200_before(http_rows, "src", 10**18)

    t_src_drop = None
    if t_src_last is not None:
        for r in http_rows:
            r_ts = r.get("ts_ms")
            if r["target"] == "src" and isinstance(r_ts, int) and r_ts >= t_src_last and r["status"] != 200:
                t_src_drop = r["ts_ms"]
                break
    t_dst_first = _first_200_after(http_rows, "dst", -1)
    if t_src_drop is not None and t_dst_first is not None:
        return min(t_dst_first, t_src_drop)
    return t_dst_first or t_src_drop or (http_rows[0]["ts_ms"] if http_rows else None)

def _min_max_ts(rows, key="ts_ms"):
    # Find timestamp bounds.
    vals = [r.get(key) for r in rows if isinstance(r, dict) and isinstance(r.get(key), int)]
    if not vals:
        return None, None
    return min(vals), max(vals)

def _longest_down_phase(rows, target, t_start, t_end, is_down):
    # Find the longest downtime phase.
    max_dur = None
    cur_start = None
    last_down_ts = None
    for r in rows:
        if r.get("target") != target:
            continue
        ts = r.get("ts_ms")
        if not isinstance(ts, int) or ts < t_start or ts > t_end:
            continue
        if is_down(r):
            if cur_start is None:
                cur_start = ts
            last_down_ts = ts
        else:
            if cur_start is not None and last_down_ts is not None:
                dur = last_down_ts - cur_start
                if max_dur is None or dur > max_dur:
                    max_dur = dur
            cur_start = None
            last_down_ts = None
    if cur_start is not None and last_down_ts is not None:
        dur = last_down_ts - cur_start
        if max_dur is None or dur > max_dur:
            max_dur = dur
    return max_dur

def _vip_http_counts_window(http_rows, cutover, window_ms):
    # Count VIP HTTP samples.
    if cutover is None:
        return {
            "vip_http_samples_before": None,
            "vip_http_200_before": None,
            "vip_http_err_before": None,
            "vip_http_transport_err_before": None,
            "vip_http_non_200_before": None,
            "vip_http_samples_after": None,
            "vip_http_200_after": None,
            "vip_http_err_after": None,
            "vip_http_transport_err_after": None,
            "vip_http_non_200_after": None,
        }
    t_start = cutover - window_ms
    t_end = cutover + window_ms
    counts = {
        "vip_http_samples_before": 0,
        "vip_http_200_before": 0,
        "vip_http_err_before": 0,
        "vip_http_transport_err_before": 0,
        "vip_http_non_200_before": 0,
        "vip_http_samples_after": 0,
        "vip_http_200_after": 0,
        "vip_http_err_after": 0,
        "vip_http_transport_err_after": 0,
        "vip_http_non_200_after": 0,
    }
    for r in http_rows:
        if r.get("target") != "vip":
            continue
        ts = r.get("ts_ms")
        if not isinstance(ts, int) or ts < t_start or ts > t_end:
            continue
        side = "before" if ts <= cutover else "after"
        status = r.get("status")
        counts[f"vip_http_samples_{side}"] += 1
        if status == 200:
            counts[f"vip_http_200_{side}"] += 1
        else:
            counts[f"vip_http_err_{side}"] += 1
            if isinstance(status, int):
                counts[f"vip_http_non_200_{side}"] += 1
            else:
                counts[f"vip_http_transport_err_{side}"] += 1
    return counts


def _vip_l4_counts_window(l4_rows, cutover, window_ms):
    # Count VIP L4 samples.
    if cutover is None:
        return {
            "vip_l4_samples_before": None,
            "vip_l4_up_before": None,
            "vip_l4_down_before": None,
            "vip_l4_samples_after": None,
            "vip_l4_up_after": None,
            "vip_l4_down_after": None,
        }
    t_start = cutover - window_ms
    t_end = cutover + window_ms
    counts = {
        "vip_l4_samples_before": 0,
        "vip_l4_up_before": 0,
        "vip_l4_down_before": 0,
        "vip_l4_samples_after": 0,
        "vip_l4_up_after": 0,
        "vip_l4_down_after": 0,
    }
    for r in l4_rows:
        if r.get("target") != "vip":
            continue
        ts = r.get("ts_ms")
        if not isinstance(ts, int) or ts < t_start or ts > t_end:
            continue
        side = "before" if ts <= cutover else "after"
        state = str(r.get("state") or "").strip().lower()
        counts[f"vip_l4_samples_{side}"] += 1
        if state == "up":
            counts[f"vip_l4_up_{side}"] += 1
        elif state == "down":
            counts[f"vip_l4_down_{side}"] += 1
    return counts


def _median_interval_ms(rows, target):
    # Compute the median sample interval.
    deltas = []
    last = None
    for r in rows:
        if r.get("target") != target:
            continue
        ts = r.get("ts_ms")
        if not isinstance(ts, int):
            continue
        if isinstance(last, int) and ts > last:
            deltas.append(ts - last)
        last = ts
    if not deltas:
        return None
    return round(float(statistics.median(deltas)), 3)


def _segment_cutover_tolerance_ms(sampling_floor_ms):
    # Compute cutover tolerance.
    floor = _safe_num(sampling_floor_ms)
    if floor is None or floor <= 0:
        return 2000
    dynamic = int(round(float(floor) * 40.0))
    return max(2000, min(10000, dynamic))


def _safe_num(value):
    # Parse an optional number.
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return None


def _transfer_stats(events, prefix: str, bytes_field: str):
    # Aggregate transfer statistics.
    by_name = defaultdict(lambda: {
        "bytes_total": 0,
        "duration_ms": 0,
        "disconnects": 0,
        "max_gap_ms": None,
        "_last_progress_ts": None,
    })
    for ev in sorted((events or []), key=lambda x: x.get("ts_ms", 0)):
        if not isinstance(ev, dict):
            continue
        typ = ev.get("type")
        name = ev.get("name")
        if not name:
            continue
        cur = by_name[name]
        if typ == f"{prefix}_progress":
            ts = ev.get("ts_ms")
            if isinstance(ts, int):
                prev = cur["_last_progress_ts"]
                if isinstance(prev, int):
                    gap = ts - prev
                    if cur["max_gap_ms"] is None or gap > cur["max_gap_ms"]:
                        cur["max_gap_ms"] = gap
                cur["_last_progress_ts"] = ts
        elif typ == f"{prefix}_done":
            b = _safe_num(ev.get(bytes_field))
            d = _safe_num(ev.get("total_ms"))
            cur["bytes_total"] += int(b or 0)
            cur["duration_ms"] += int(d or 0)
        elif typ == f"{prefix}_disconnect":
            b = _safe_num(ev.get(bytes_field))
            d = _safe_num(ev.get("duration_ms"))
            cur["bytes_total"] += int(b or 0)
            cur["duration_ms"] += int(d or 0)
            cur["disconnects"] += 1

    out_by_name = {}
    agg = {"bytes_total": 0, "duration_ms": 0, "disconnects": 0, "max_gap_ms": None, "avg_bps": None}
    for name, cur in by_name.items():
        duration_ms = int(cur["duration_ms"])
        bytes_total = int(cur["bytes_total"])
        avg_bps = round((bytes_total * 1000.0) / duration_ms, 3) if duration_ms > 0 else None
        out = {
            "bytes_total": bytes_total,
            "duration_ms": duration_ms,
            "avg_bps": avg_bps,
            "disconnects": int(cur["disconnects"]),
            "max_gap_ms": cur["max_gap_ms"],
        }
        out_by_name[name] = out
        agg["bytes_total"] += out["bytes_total"]
        agg["duration_ms"] += out["duration_ms"]
        agg["disconnects"] += out["disconnects"]
        if out["max_gap_ms"] is not None and (agg["max_gap_ms"] is None or out["max_gap_ms"] > agg["max_gap_ms"]):
            agg["max_gap_ms"] = out["max_gap_ms"]

    if agg["duration_ms"] > 0:
        agg["avg_bps"] = round((agg["bytes_total"] * 1000.0) / agg["duration_ms"], 3)
    return {"by_name": out_by_name, "aggregate": agg}


def _stream_stats(events):
    # Aggregate stream statistics.
    by_name = defaultdict(lambda: {
        "bytes_total": 0,
        "duration_ms": 0,
        "disconnects": 0,
        "max_gap_ms": None,
        "_last_progress_ts": None,
    })
    for ev in sorted((events or []), key=lambda x: x.get("ts_ms", 0)):
        if not isinstance(ev, dict):
            continue
        typ = ev.get("type")
        name = ev.get("name")
        if not name:
            continue
        cur = by_name[name]
        if typ in ("stream_line", "stream_progress"):
            ts = ev.get("ts_ms")
            if isinstance(ts, int):
                prev = cur["_last_progress_ts"]
                if isinstance(prev, int):
                    gap = ts - prev
                    if cur["max_gap_ms"] is None or gap > cur["max_gap_ms"]:
                        cur["max_gap_ms"] = gap
                cur["_last_progress_ts"] = ts
        elif typ == "stream_disconnect":
            b = _safe_num(ev.get("bytes"))
            d = _safe_num(ev.get("duration_ms"))
            cur["bytes_total"] += int(b or 0)
            cur["duration_ms"] += int(d or 0)
            cur["disconnects"] += 1

    out_by_name = {}
    agg = {"bytes_total": 0, "duration_ms": 0, "disconnects": 0, "max_gap_ms": None, "avg_bps": None}
    for name, cur in by_name.items():
        duration_ms = int(cur["duration_ms"])
        bytes_total = int(cur["bytes_total"])
        avg_bps = round((bytes_total * 1000.0) / duration_ms, 3) if duration_ms > 0 else None
        out = {
            "bytes_total": bytes_total,
            "duration_ms": duration_ms,
            "avg_bps": avg_bps,
            "disconnects": int(cur["disconnects"]),
            "max_gap_ms": cur["max_gap_ms"],
        }
        out_by_name[name] = out
        agg["bytes_total"] += out["bytes_total"]
        agg["duration_ms"] += out["duration_ms"]
        agg["disconnects"] += out["disconnects"]
        if out["max_gap_ms"] is not None and (agg["max_gap_ms"] is None or out["max_gap_ms"] > agg["max_gap_ms"]):
            agg["max_gap_ms"] = out["max_gap_ms"]
    if agg["duration_ms"] > 0:
        agg["avg_bps"] = round((agg["bytes_total"] * 1000.0) / agg["duration_ms"], 3)
    return {"by_name": out_by_name, "aggregate": agg}

def _compute_metrics(http_rows, l4_rows, cutover):
    # Compute metrics.

    t_src_last = _last_200_before(http_rows, "src", cutover)
    t_dst_first = _first_200_after(http_rows, "dst", cutover)
    http_dt = (None if (t_src_last is None or t_dst_first is None) else (t_dst_first - t_src_last))


    t_l4_src_last = _last_up_before(l4_rows, "src", cutover)
    t_l4_dst_first = _first_up_after(l4_rows, "dst", cutover)
    l4_dt = (None if (t_l4_src_last is None or t_l4_dst_first is None) else (t_l4_dst_first - t_l4_src_last))


    t_vip_last = _last_200_before(http_rows, "vip", cutover)
    t_vip_first = _first_200_after(http_rows, "vip", cutover)
    vip_http_dt = (None if (t_vip_last is None or t_vip_first is None) else (t_vip_first - t_vip_last))


    t_l4_last = _last_up_before(l4_rows, "vip", cutover)
    t_l4_first = _first_up_after(l4_rows, "vip", cutover)
    vip_l4_dt = (None if (t_l4_last is None or t_l4_first is None) else (t_l4_first - t_l4_last))

    return http_dt, l4_dt, vip_http_dt, vip_l4_dt, t_vip_last, t_vip_first, t_l4_last, t_l4_first, t_l4_src_last, t_l4_dst_first

def analyze_run(base_out, events_path=None):
    # Analyze one run.
    http_path = f"{base_out}-http.csv"
    l4_path   = f"{base_out}-l4.csv"
    stream_path = f"{base_out}-stream.ndjson"
    download_path = f"{base_out}-download.ndjson"
    upload_path = f"{base_out}-upload.ndjson"

    http_rows = _csv_to_dicts_http(_load_csv_rows(http_path))
    l4_rows   = _csv_to_dicts_l4(_load_csv_rows(l4_path))
    events    = _load_ndjson(events_path) if events_path else []

    if not http_rows or not l4_rows:

        print("Analyse: unvollständige Daten (http oder l4 fehlen).")
        return 2


    http_rows.sort(key=lambda r: r.get("ts_ms", 0))
    l4_rows.sort(key=lambda r: r.get("ts_ms", 0))


    clock_offsets = _extract_clock_offsets(events)
    cutover_pick = _pick_cutover_event(events, clock_offsets=clock_offsets)
    cutover_event = cutover_pick["ts_ms"] if cutover_pick else None
    cutover_event_raw = cutover_pick["ts_raw_ms"] if cutover_pick else None
    cutover_event_name = cutover_pick["event"] if cutover_pick else None
    cutover_event_clock_domain = cutover_pick["clock_domain"] if cutover_pick else None
    cutover = cutover_event
    cutover_strategy = "events"
    if cutover_pick and cutover_event_raw is not None and cutover_event is not None and cutover_event_raw != cutover_event:
        cutover_strategy = "events(offset_corrected)"

    t_min_http, t_max_http = _min_max_ts(http_rows, "ts_ms")
    t_min_l4, t_max_l4 = _min_max_ts(l4_rows, "ts_ms")
    t_min = min([t for t in (t_min_http, t_min_l4) if t is not None], default=None)
    t_max = max([t for t in (t_max_http, t_max_l4) if t is not None], default=None)

    if cutover is None:
        cutover = _heuristic_cutover_from_http(http_rows)
        cutover_strategy = "heuristic(no_events)"
    elif t_min is not None and t_max is not None and (cutover < t_min or cutover > t_max):


        cutover = _heuristic_cutover_from_http(http_rows)
        cutover_strategy = "heuristic(event_out_of_range)"

    (
        http_dt,
        l4_dt,
        vip_http_gap_dt,
        vip_l4_gap_dt,
        t_vip_last,
        t_vip_first,
        t_l4_last,
        t_l4_first,
        t_l4_src_last,
        t_l4_dst_first,
    ) = _compute_metrics(http_rows, l4_rows, cutover)
    sampling_floor_http_ms = _median_interval_ms(http_rows, "vip")
    sampling_floor_l4_ms = _median_interval_ms(l4_rows, "vip")
    seg_tol_http_ms = _segment_cutover_tolerance_ms(sampling_floor_http_ms)
    seg_tol_l4_ms = _segment_cutover_tolerance_ms(sampling_floor_l4_ms)

    has_vip_http_rows = any(r.get("target") == "vip" for r in http_rows)
    has_vip_l4_rows = any(r.get("target") == "vip" for r in l4_rows)
    vip_http_segments = _collect_down_segments(http_rows, "vip", lambda r: r.get("status") != 200)
    vip_l4_segments = _collect_down_segments(l4_rows, "vip", lambda r: r.get("state") == "down")
    vip_http_seg = _select_client_visible_segment(vip_http_segments, cutover_ms=cutover, tolerance_ms=seg_tol_http_ms)
    vip_l4_seg = _select_client_visible_segment(vip_l4_segments, cutover_ms=cutover, tolerance_ms=seg_tol_l4_ms)
    vip_http_dt = vip_http_seg.get("duration_ms") if isinstance(vip_http_seg, dict) else None
    vip_l4_dt = vip_l4_seg.get("duration_ms") if isinstance(vip_l4_seg, dict) else None


    if cutover_event is not None and str(cutover_strategy).startswith("events") and (http_dt is None and l4_dt is None and vip_http_gap_dt is None and vip_l4_gap_dt is None):
        alt_cutover = _heuristic_cutover_from_http(http_rows)
        if alt_cutover is not None:
            (
                alt_http_dt,
                alt_l4_dt,
                alt_vip_http_gap_dt,
                alt_vip_l4_gap_dt,
                alt_t_vip_last,
                alt_t_vip_first,
                alt_t_l4_last,
                alt_t_l4_first,
                alt_t_l4_src_last,
                alt_t_l4_dst_first,
            ) = _compute_metrics(http_rows, l4_rows, alt_cutover)
            if any(v is not None for v in (alt_http_dt, alt_l4_dt, alt_vip_http_gap_dt, alt_vip_l4_gap_dt)):
                cutover = alt_cutover
                cutover_strategy = "heuristic(event_no_downtime)"
                http_dt, l4_dt, vip_http_gap_dt, vip_l4_gap_dt = alt_http_dt, alt_l4_dt, alt_vip_http_gap_dt, alt_vip_l4_gap_dt
                t_vip_last, t_vip_first, t_l4_last, t_l4_first = alt_t_vip_last, alt_t_vip_first, alt_t_l4_last, alt_t_l4_first
                t_l4_src_last, t_l4_dst_first = alt_t_l4_src_last, alt_t_l4_dst_first
                vip_http_seg = _select_client_visible_segment(vip_http_segments, cutover_ms=cutover, tolerance_ms=seg_tol_http_ms)
                vip_l4_seg = _select_client_visible_segment(vip_l4_segments, cutover_ms=cutover, tolerance_ms=seg_tol_l4_ms)
                vip_http_dt = vip_http_seg.get("duration_ms") if isinstance(vip_http_seg, dict) else None
                vip_l4_dt = vip_l4_seg.get("duration_ms") if isinstance(vip_l4_seg, dict) else None


    lat_src = _latency_stats(http_rows, "src")
    lat_dst = _latency_stats(http_rows, "dst")
    lat_vip = _latency_stats(http_rows, "vip")


    stream_events = _load_ndjson(stream_path)
    download_events = _load_ndjson(download_path)
    upload_events = _load_ndjson(upload_path)
    stream_stats = _stream_stats(stream_events)
    download_stats = _transfer_stats(download_events, "download", "bytes_total")
    upload_stats = _transfer_stats(upload_events, "upload", "bytes_sent")


    window_ms = 10_000
    if cutover is not None:
        t_start = cutover - window_ms
        t_end = cutover + window_ms
        vip_http_downphase_ms = _longest_down_phase(
            http_rows, "vip", t_start, t_end, lambda r: r.get("status") != 200
        )
        vip_l4_downphase_ms = _longest_down_phase(
            l4_rows, "vip", t_start, t_end, lambda r: r.get("state") == "down"
        )
    else:
        vip_http_downphase_ms = None
        vip_l4_downphase_ms = None

    vip_http_counts = _vip_http_counts_window(http_rows, cutover if has_vip_http_rows else None, window_ms)
    vip_l4_counts = _vip_l4_counts_window(l4_rows, cutover if has_vip_l4_rows else None, window_ms)
    control_run = any((ev or {}).get("event") == "control_run" for ev in events)
    final_dump_start_ms = _first_event_ts(events, "final_dump_start", clock_offsets)
    final_dump_done_ms = _first_event_ts(events, "final_dump_done", clock_offsets)
    transfer_start_ms = _first_event_ts(events, "transfer_start", clock_offsets)
    transfer_done_ms = _first_event_ts(events, "transfer_done", clock_offsets)
    checkpoint_start_ms = _first_event_ts(events, "checkpoint_start", clock_offsets)
    checkpoint_done_ms = _first_event_ts(events, "checkpoint_done", clock_offsets)
    vip_prepare_start_ms = _first_event_ts(events, "vip_prepare_start", clock_offsets)
    vip_prepare_done_ms = _first_event_ts(events, "vip_prepare_done", clock_offsets)
    dest_container_cleanup_start_ms = _first_event_ts(events, "dest_container_cleanup_start", clock_offsets)
    dest_container_cleanup_done_ms = _first_event_ts(events, "dest_container_cleanup_done", clock_offsets)
    restore_start_event_ms = _first_event_ts(events, "restore_start", clock_offsets)
    restore_done_event_ms = _first_event_ts(events, "restore_done", clock_offsets)
    restore_exec_start_ms = _first_event_ts_any(events, ("restore_exec_start",), clock_offsets)
    restore_exec_done_ms = _first_event_ts_any(events, ("restore_exec_done",), clock_offsets)
    dest_readiness_start_ms = _first_event_ts(events, "dest_readiness_wait_start", clock_offsets)
    dest_readiness_ok_ms = _first_event_ts(events, "dest_readiness_ok", clock_offsets)
    postcopy_warmup_start_ms = _first_event_ts(events, "postcopy_warmup_start", clock_offsets)
    postcopy_warmup_done_ms = _first_event_ts(events, "postcopy_warmup_done", clock_offsets)
    postcopy_src_forward_start_ms = _first_event_ts(events, "postcopy_src_forward_start", clock_offsets)
    postcopy_src_forward_ready_ms = _first_event_ts(events, "postcopy_src_forward_ready", clock_offsets)
    postcopy_src_forward_stop_start_ms = _first_event_ts(events, "postcopy_src_forward_stop_start", clock_offsets)
    postcopy_src_forward_stop_done_ms = _first_event_ts(events, "postcopy_src_forward_stop_done", clock_offsets)
    postcopy_src_forward_mode = _first_event_field(events, "postcopy_src_forward_start", "mode")
    if postcopy_src_forward_mode is None:
        postcopy_src_forward_mode = _first_event_field(events, "postcopy_src_forward_ready", "mode")
    postcopy_warmup_impl = _first_event_field(events, "postcopy_warmup_start", "impl")
    if postcopy_warmup_impl is None:
        postcopy_warmup_impl = _first_event_field(events, "postcopy_warmup_done", "impl")
    postcopy_warmup_url_count = _first_event_field_int(events, "postcopy_warmup_start", "url_count")
    postcopy_warmup_requests = _first_event_field_int(events, "postcopy_warmup_done", "requests")
    postcopy_warmup_failures = _first_event_field_int(events, "postcopy_warmup_done", "failures")
    postcopy_warmup_budget_hit = _first_event_field_int(events, "postcopy_warmup_done", "budget_hit")
    postcopy_warmup_remote_elapsed_ms = _first_event_field_int(events, "postcopy_warmup_done", "remote_elapsed_ms")
    postcopy_warmup_completed_rounds = _first_event_field_int(events, "postcopy_warmup_done", "completed_rounds")
    postcopy_warmup_configured_rounds = _first_event_field_int(events, "postcopy_warmup_done", "configured_rounds")
    postcopy_warmup_transport_error = _first_event_field_int(events, "postcopy_warmup_done", "transport_error")
    vip_cutover_start_ms = _first_event_ts(events, "vip_cutover_start", clock_offsets)
    vip_cutover_done_ms = _first_event_ts(events, "vip_cutover_done", clock_offsets)
    health_wait_start_ms = _first_event_ts(events, "health_wait_start", clock_offsets)
    health_ok_ms = _first_event_ts(events, "health_ok", clock_offsets)
    transfer_mode = _first_event_field(events, "transfer_start", "mode")
    transfer_note = _first_event_field(events, "transfer_done", "note")
    transfer_verify_mode = _first_event_field(events, "transfer_done", "verify_mode")
    sanity_flags = []
    if isinstance(vip_http_dt, (int, float)) and isinstance(vip_http_gap_dt, (int, float)):
        if abs(float(vip_http_dt) - float(vip_http_gap_dt)) > max(500.0, float(vip_http_dt) * 2.0):
            sanity_flags.append("vip_http_segment_vs_cutover_gap_large_delta")
    if isinstance(vip_l4_dt, (int, float)) and isinstance(vip_l4_gap_dt, (int, float)):
        if abs(float(vip_l4_dt) - float(vip_l4_gap_dt)) > max(500.0, float(vip_l4_dt) * 2.0):
            sanity_flags.append("vip_l4_segment_vs_cutover_gap_large_delta")

    breakdown_markers = {
        "final_dump_start_ms_event": final_dump_start_ms,
        "final_dump_done_ms_event": final_dump_done_ms,
        "transfer_start_ms_event": transfer_start_ms,
        "transfer_done_ms_event": transfer_done_ms,
        "checkpoint_start_ms_event": checkpoint_start_ms,
        "checkpoint_done_ms_event": checkpoint_done_ms,
        "restore_start_ms_event": restore_start_event_ms,
        "restore_done_ms_event": restore_done_event_ms,
        "restore_exec_start_ms_event": restore_exec_start_ms,
        "restore_exec_done_ms_event": restore_exec_done_ms,
        "dest_readiness_wait_start_ms_event": dest_readiness_start_ms,
        "dest_readiness_ok_ms_event": dest_readiness_ok_ms,
        "postcopy_warmup_start_ms_event": postcopy_warmup_start_ms,
        "postcopy_warmup_done_ms_event": postcopy_warmup_done_ms,
        "postcopy_src_forward_start_ms_event": postcopy_src_forward_start_ms,
        "postcopy_src_forward_ready_ms_event": postcopy_src_forward_ready_ms,
        "postcopy_src_forward_stop_start_ms_event": postcopy_src_forward_stop_start_ms,
        "postcopy_src_forward_stop_done_ms_event": postcopy_src_forward_stop_done_ms,
        "vip_cutover_start_ms_event": vip_cutover_start_ms,
        "vip_cutover_done_ms_event": vip_cutover_done_ms,
        "health_wait_start_ms_event": health_wait_start_ms,
        "health_ok_ms_event": health_ok_ms,
        "vip_http_segment_start_ms": vip_http_seg.get("start_ms") if isinstance(vip_http_seg, dict) else None,
        "vip_http_segment_end_ms": vip_http_seg.get("end_ms") if isinstance(vip_http_seg, dict) else None,
    }
    migration_method = _infer_migration_method(breakdown_markers)
    (
        vip_http_client_window_start_ms,
        vip_http_client_window_end_ms,
        vip_http_client_window_quality_flags,
    ) = _migration_relevant_vip_http_window(
        migration_method,
        final_dump_start_ms=final_dump_start_ms,
        checkpoint_start_ms=checkpoint_start_ms,
        transfer_start_ms=transfer_start_ms,
        restore_start_ms=restore_start_event_ms,
        health_ok_ms=health_ok_ms,
        cutover_ms=cutover,
        http_rows=http_rows,
        fallback_window_ms=window_ms,
    )
    vip_http_client_visible_segments = _clip_down_segments_to_window(
        vip_http_segments,
        vip_http_client_window_start_ms,
        vip_http_client_window_end_ms,
    )
    vip_http_client_visible = _client_visible_down_metrics(vip_http_client_visible_segments)
    breakdown_markers["vip_http_client_visible_down_segments"] = vip_http_client_visible_segments
    downtime_breakdown = _build_downtime_breakdown(breakdown_markers, method_hint=migration_method)


    report = {
        "migration_method": migration_method,
        "cutover_ms": cutover,
        "cutover_ms_event": cutover_event,
        "cutover_ms_event_raw": cutover_event_raw,
        "cutover_event_name": cutover_event_name,
        "cutover_event_clock_domain": cutover_event_clock_domain,
        "cutover_strategy": cutover_strategy,
        "clock_offsets_ms": clock_offsets,
        "http_downtime_ms": http_dt,
        "l4_downtime_ms": l4_dt,
        "vip_http_client_visible_total_down_ms": vip_http_client_visible["total_down_ms"] if has_vip_http_rows else None,
        "vip_http_client_visible_down_segments": vip_http_client_visible["down_segments"] if has_vip_http_rows else None,
        "vip_http_client_visible_outage_span_ms": vip_http_client_visible["outage_span_ms"] if has_vip_http_rows else None,
        "vip_http_client_visible_first_down_ms": vip_http_client_visible["first_down_ms"] if has_vip_http_rows else None,
        "vip_http_client_visible_final_recovery_ms": vip_http_client_visible["final_recovery_ms"] if has_vip_http_rows else None,
        "vip_http_client_visible_window_start_ms": vip_http_client_window_start_ms if has_vip_http_rows else None,
        "vip_http_client_visible_window_end_ms": vip_http_client_window_end_ms if has_vip_http_rows else None,
        "vip_http_client_visible_window_quality_flags": vip_http_client_window_quality_flags if has_vip_http_rows else [],
        "vip_http_client_visible_segments": vip_http_client_visible_segments if has_vip_http_rows else [],
        "vip_http_cutover_near_downtime_ms": vip_http_dt,
        "vip_http_downtime_ms": vip_http_dt,
        "vip_l4_downtime_ms": vip_l4_dt,
        "vip_http_cutover_gap_ms": vip_http_gap_dt,
        "vip_l4_cutover_gap_ms": vip_l4_gap_dt,
        "vip_http_downphase_ms": vip_http_downphase_ms,
        "vip_l4_downphase_ms": vip_l4_downphase_ms,
        "control_run": control_run,
        "sampling_floor_http_ms": sampling_floor_http_ms,
        "sampling_floor_l4_ms": sampling_floor_l4_ms,
        "segment_cutover_tolerance_http_ms": seg_tol_http_ms,
        "segment_cutover_tolerance_l4_ms": seg_tol_l4_ms,
        "cutover_window_ms": window_ms,
        "downtime_interpretation": "sampling_floor_control_run" if control_run else "migration_downtime",
        "sanity_flags": sanity_flags,
        "final_dump_start_ms_event": final_dump_start_ms,
        "final_dump_done_ms_event": final_dump_done_ms,
        "transfer_start_ms_event": transfer_start_ms,
        "transfer_done_ms_event": transfer_done_ms,
        "checkpoint_start_ms_event": checkpoint_start_ms,
        "checkpoint_done_ms_event": checkpoint_done_ms,
        "vip_prepare_start_ms_event": vip_prepare_start_ms,
        "vip_prepare_done_ms_event": vip_prepare_done_ms,
        "dest_container_cleanup_start_ms_event": dest_container_cleanup_start_ms,
        "dest_container_cleanup_done_ms_event": dest_container_cleanup_done_ms,
        "restore_start_ms_event": restore_start_event_ms,
        "restore_done_ms_event": restore_done_event_ms,
        "restore_exec_start_ms_event": restore_exec_start_ms,
        "restore_exec_done_ms_event": restore_exec_done_ms,
        "dest_readiness_wait_start_ms_event": dest_readiness_start_ms,
        "dest_readiness_ok_ms_event": dest_readiness_ok_ms,
        "postcopy_warmup_start_ms_event": postcopy_warmup_start_ms,
        "postcopy_warmup_done_ms_event": postcopy_warmup_done_ms,
        "postcopy_src_forward_start_ms_event": postcopy_src_forward_start_ms,
        "postcopy_src_forward_ready_ms_event": postcopy_src_forward_ready_ms,
        "postcopy_src_forward_stop_start_ms_event": postcopy_src_forward_stop_start_ms,
        "postcopy_src_forward_stop_done_ms_event": postcopy_src_forward_stop_done_ms,
        "vip_cutover_start_ms_event": vip_cutover_start_ms,
        "vip_cutover_done_ms_event": vip_cutover_done_ms,
        "health_wait_start_ms_event": health_wait_start_ms,
        "health_ok_ms_event": health_ok_ms,
        "precopy_transfer_mode": transfer_mode,
        "precopy_transfer_note": transfer_note,
        "precopy_transfer_verify_mode": transfer_verify_mode,
        "postcopy_checkpoint_ms": _delta_ms(checkpoint_start_ms, checkpoint_done_ms),
        "precopy_final_dump_ms": _delta_ms(final_dump_start_ms, final_dump_done_ms),
        "precopy_transfer_prepare_ms": _delta_ms(transfer_start_ms, transfer_done_ms),
        "precopy_vip_prepare_ms": _delta_ms(vip_prepare_start_ms, vip_prepare_done_ms),
        "precopy_dest_container_cleanup_ms": _delta_ms(dest_container_cleanup_start_ms, dest_container_cleanup_done_ms),
        "precopy_transfer_to_restore_ms": _delta_ms(transfer_done_ms, restore_start_event_ms),
        "precopy_restore_call_ms": _delta_ms(restore_start_event_ms, restore_done_event_ms),
        "precopy_transfer_to_restore_exec_ms": _delta_ms(transfer_done_ms, restore_exec_start_ms),
        "precopy_restore_launch_overhead_ms": _delta_ms(restore_start_event_ms, restore_exec_start_ms),
        "precopy_restore_exec_ms": _delta_ms(restore_exec_start_ms, restore_exec_done_ms),
        "precopy_restore_return_overhead_ms": _delta_ms(restore_exec_done_ms, restore_done_event_ms),
        "precopy_restore_to_cutover_ms": _delta_ms(restore_done_event_ms, vip_cutover_start_ms),
        "precopy_restore_exec_to_cutover_ms": _delta_ms(restore_exec_done_ms, vip_cutover_start_ms),
        "postcopy_src_forward_mode": postcopy_src_forward_mode,
        "postcopy_src_forward_setup_ms": _delta_ms(postcopy_src_forward_start_ms, postcopy_src_forward_ready_ms),
        "postcopy_src_forward_active_to_cutover_ms": _delta_ms(postcopy_src_forward_ready_ms, vip_cutover_start_ms),
        "postcopy_src_forward_stop_ms": _delta_ms(postcopy_src_forward_stop_start_ms, postcopy_src_forward_stop_done_ms),
        "postcopy_restore_to_readiness_ms": _delta_ms(restore_done_event_ms, dest_readiness_ok_ms),
        "postcopy_readiness_gate_ms": _delta_ms(dest_readiness_start_ms, dest_readiness_ok_ms),
        "postcopy_readiness_to_warmup_done_ms": _delta_ms(dest_readiness_ok_ms, postcopy_warmup_done_ms),
        "postcopy_warmup_duration_ms": _delta_ms(postcopy_warmup_start_ms, postcopy_warmup_done_ms),
        "postcopy_warmup_impl": postcopy_warmup_impl,
        "postcopy_warmup_url_count": postcopy_warmup_url_count,
        "postcopy_warmup_requests": postcopy_warmup_requests,
        "postcopy_warmup_failures": postcopy_warmup_failures,
        "postcopy_warmup_budget_hit": postcopy_warmup_budget_hit,
        "postcopy_warmup_remote_elapsed_ms": postcopy_warmup_remote_elapsed_ms,
        "postcopy_warmup_completed_rounds": postcopy_warmup_completed_rounds,
        "postcopy_warmup_configured_rounds": postcopy_warmup_configured_rounds,
        "postcopy_warmup_transport_error": postcopy_warmup_transport_error,
        "postcopy_warmup_to_cutover_ms": _delta_ms(postcopy_warmup_done_ms, vip_cutover_start_ms),
        "postcopy_cutover_duration_ms": _delta_ms(vip_cutover_start_ms, vip_cutover_done_ms),
        "postcopy_cutover_to_health_ok_ms": _delta_ms(vip_cutover_start_ms, health_ok_ms),
        "postcopy_restore_to_health_ok_ms": _delta_ms(restore_start_event_ms, health_ok_ms),
        "t_vip_last_200": t_vip_last,
        "t_vip_first_200": t_vip_first,
        "t_l4_src_last_up": t_l4_src_last,
        "t_l4_dst_first_up": t_l4_dst_first,
        "t_l4_vip_last_up": t_l4_last,
        "t_l4_vip_first_up": t_l4_first,
        "vip_http_cutover_near_segment_start_ms": vip_http_seg.get("start_ms") if isinstance(vip_http_seg, dict) else None,
        "vip_http_cutover_near_segment_end_ms": vip_http_seg.get("end_ms") if isinstance(vip_http_seg, dict) else None,
        "vip_http_segment_start_ms": vip_http_seg.get("start_ms") if isinstance(vip_http_seg, dict) else None,
        "vip_http_segment_end_ms": vip_http_seg.get("end_ms") if isinstance(vip_http_seg, dict) else None,
        "vip_l4_segment_start_ms": vip_l4_seg.get("start_ms") if isinstance(vip_l4_seg, dict) else None,
        "vip_l4_segment_end_ms": vip_l4_seg.get("end_ms") if isinstance(vip_l4_seg, dict) else None,
        "downtime_breakdown": downtime_breakdown,
        **vip_http_counts,
        **vip_l4_counts,
        "latency": {"src": lat_src, "dst": lat_dst, "vip": lat_vip},
        "stream": {
            "disconnects": stream_stats["aggregate"]["disconnects"],
            "max_gap_ms": stream_stats["aggregate"]["max_gap_ms"],
            "bytes_total": stream_stats["aggregate"]["bytes_total"],
            "duration_ms": stream_stats["aggregate"]["duration_ms"],
            "avg_bps": stream_stats["aggregate"]["avg_bps"],
            "by_name": stream_stats["by_name"],
            "aggregate": stream_stats["aggregate"],
        },
        "download": download_stats,
        "upload": upload_stats,
    }

    print(json.dumps(report, indent=2))
    print("\n=== Downtime Summary ===")
    print(f"HTTP (src last 200 -> dst first 200): {http_dt} ms")
    print(f"L4   (src last up  -> dst first up ): {l4_dt} ms")
    print(f"VIP HTTP client-visible total down: {vip_http_client_visible['total_down_ms']} ms in {vip_http_client_visible['down_segments']} segment(s)")
    print(f"VIP HTTP client-visible outage span: {vip_http_client_visible['outage_span_ms']} ms")
    print(f"VIP HTTP cutover-near downtime segment: {vip_http_dt} ms")
    print(f"VIP L4 downtime  (client-visible segment): {vip_l4_dt} ms")
    print(f"VIP HTTP cutover-gap (legacy): {vip_http_gap_dt} ms")
    print(f"VIP L4 cutover-gap  (legacy): {vip_l4_gap_dt} ms")
    print(
        "VIP HTTP window counts: "
        f"samples(before/after)={vip_http_counts['vip_http_samples_before']}/{vip_http_counts['vip_http_samples_after']}, "
        f"200={vip_http_counts['vip_http_200_before']}/{vip_http_counts['vip_http_200_after']}, "
        f"ERR={vip_http_counts['vip_http_transport_err_before']}/{vip_http_counts['vip_http_transport_err_after']}, "
        f"non200={vip_http_counts['vip_http_non_200_before']}/{vip_http_counts['vip_http_non_200_after']}"
    )
    print(
        "VIP L4 window counts: "
        f"samples(before/after)={vip_l4_counts['vip_l4_samples_before']}/{vip_l4_counts['vip_l4_samples_after']}, "
        f"up={vip_l4_counts['vip_l4_up_before']}/{vip_l4_counts['vip_l4_up_after']}, "
        f"down={vip_l4_counts['vip_l4_down_before']}/{vip_l4_counts['vip_l4_down_after']}"
    )
    print(f"Latency p50/avg:  src={lat_src}  dst={lat_dst}  vip={lat_vip}")
    print(
        "Stream: disconnects="
        f"{stream_stats['aggregate']['disconnects']}, max_gap_ms={stream_stats['aggregate']['max_gap_ms']}"
    )
    print(
        "Download: bytes_total="
        f"{download_stats['aggregate']['bytes_total']}, avg_bps={download_stats['aggregate']['avg_bps']}, "
        f"disconnects={download_stats['aggregate']['disconnects']}"
    )
    print(
        "Upload: bytes_total="
        f"{upload_stats['aggregate']['bytes_total']}, avg_bps={upload_stats['aggregate']['avg_bps']}, "
        f"disconnects={upload_stats['aggregate']['disconnects']}"
    )
    return 0


