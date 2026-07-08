"""Legacy-compatible default configuration owned by core.

These values remain shaped for the current legacy CLI env.yaml loader, but the
data itself is CLI-free so core config helpers can use it without importing
the CLI package.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULTS: dict[str, Any] = {
    "repo_path": "~/CLM",
    "hosts": {
        "monitor": {"host": "local", "ip": "192.168.13.20"},
        "source": {"host": "benke1", "ip": "192.168.13.10"},
        "dest": {"host": "benke2", "ip": "192.168.13.15"},
    },
    "paths": {
        "share_root": "/mnt/criu",
        "runs_root": "/mnt/criu/runs",
        "logs_root": "/mnt/criu/logs",
    },
    "vip": {
        "addr": "192.168.13.50",
        "cidr": "/24",
        "port": 8080,
        "if_source": "enp1s0",
        "if_dest": "enp1s0",
    },
    "postcopy": {
        "lazy_port": 27027,
        "src_lazy_ip": "192.168.13.10",
        "src_forwarding_enabled": 1,
        "src_forwarding_mode": "iptables_dnat",
        "src_forwarding_target_host": "192.168.13.15",
        "src_forwarding_target_port": 8080,
        "readiness_urls": [
            "http://192.168.13.15:8080/health",
        ],
        "readiness_stable_successes": 3,
        "readiness_interval_ms": 200,
        "readiness_timeout_ms": 10000,
        "probe_max_time_s": 2,
        "warmup_urls": [
            "http://192.168.13.15:8080/ready",
            "http://192.168.13.15:8080/counter",
        ],
        "warmup_rounds": 1,
        "warmup_interval_ms": 0,
        "warmup_max_duration_ms": 400,
    },
    "container": {
        "name": "testweb",
        "image": "benke/testweb:phase3",
        "bundle": "/mnt/criu/runc-bundle",
        "gunicorn": {
            "workers": 1,
            "threads": 4,
        },
    },
    "migration": {
        "net_mode": "host",
        "container_ip_dest": "172.18.0.5",
        "vip_garp_count": 3,
        "vip_garp_interval_ms": 200,
        "vip_garp_mode": "A",
        "vip_conntrack_clear_src": 0,
    },
    "precopy": {
        "pre_dump_rounds": 0,
        "tcp_established": 1,
        "image_mode": "shared",
    },
    "monitor": {
        "http_interval_ms": 50,
        "http_timeout_ms": None,
        "l4_interval_ms": 50,
        "l4_timeout_ms": None,
        "enforce_timeout_below_interval": True,
        "clock_offset_samples": 3,
        "precision_mode": False,
        "enable_info_targets": True,
        "enable_counter_targets": True,
        "enable_stream_targets": True,
        "burst_window_ms": 0,
        "burst_http_interval_ms": 10,
        "burst_l4_interval_ms": 10,
        "burst_trigger_events": ["vip_cutover_start", "vip_cutover_done"],
        "stream_interval_ms": 200,
        "rotate_size_mb": 50,
    },
    "cleanup": {
        "shared_images_policy": "success_only",
        "local_images_policy": "success_only",
    },
    "load": {
        "cpu": {
            "target": "all",
            "parallel": 1,
            "sleep_ms": 1000,
            "cpu_n": 300000,
        },
        "wrk": {
            "target": "vip",
            "parallel": 1,
            "threads": 2,
            "connections": 16,
            "duration_s": 30,
            "timeout_s": 2,
            "path": "/health",
            "latency": True,
        },
        "wrk1": {
            "target": "vip",
            "parallel": 1,
            "threads": 1,
            "connections": 10,
            "duration_s": 30,
            "timeout_s": 2,
            "path": "/health",
            "latency": True,
        },
        "wrk2": {
            "target": "vip",
            "parallel": 1,
            "threads": 1,
            "connections": 20,
            "duration_s": 30,
            "timeout_s": 2,
            "path": "/health",
            "latency": True,
        },
        "wrk3": {
            "target": "vip",
            "parallel": 1,
            "threads": 1,
            "connections": 50,
            "duration_s": 30,
            "timeout_s": 2,
            "path": "/health",
            "latency": True,
        },
        "download": {
            "target": "vip",
            "parallel": 1,
            "bytes": 100 * 1024 * 1024,
            "chunk_kb": 64,
            "sleep_ms": 0,
            "pattern": "zero",
            "meta": 0,
        },
        "upload": {
            "target": "vip",
            "parallel": 1,
            "bytes": 100 * 1024 * 1024,
            "chunk_kb": 64,
            "sleep_ms": 0,
            "sink": "discard",
            "id_prefix": "clm",
        },
        "stream": {
            "target": "vip",
            "parallel": 1,
            "interval_ms": 200,
            "payload_kb": 64,
            "format": "raw",
            "limit": 0,
        },
    },
}


def legacy_defaults() -> dict[str, Any]:
    """Return a deep copy of the legacy-compatible defaults."""

    return deepcopy(DEFAULTS)


__all__ = ("DEFAULTS", "legacy_defaults")
