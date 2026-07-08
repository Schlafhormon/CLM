"""VIP traffic backend adapter for the current lab scripts."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from clm.core.config import traffic_from_legacy_env
from clm.core.models import PreflightResult, TrafficPlan
from clm.migration.traffic.base import TrafficActionResult, TrafficBackend, noop_result


class VipTrafficBackend(TrafficBackend):
    """Adapter around existing VIP/GARP/conntrack script behavior."""

    mode = "vip"

    def __init__(self, plan: Optional[TrafficPlan] = None):
        super().__init__(plan=plan or TrafficPlan(mode=self.mode))

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "VipTrafficBackend":
        return cls(traffic_from_legacy_env(dict(config)))

    def preflight(self, context: Optional[Mapping[str, Any]] = None) -> PreflightResult:
        checks = []
        blockers = []
        fields = {
            "vip addr": self.plan.vip_addr,
            "vip cidr": self.plan.vip_cidr,
            "vip port": self.plan.port,
            "source interface": (self.plan.interfaces or {}).get("source"),
            "dest interface": (self.plan.interfaces or {}).get("dest"),
        }
        for name, value in fields.items():
            ok = value not in (None, "")
            checks.append({"name": f"traffic vip {name}", "ok": ok, "detail": value or "missing"})
            if not ok:
                blockers.append(f"traffic vip {name} is required")
        return PreflightResult(checks=tuple(checks), blockers=tuple(blockers), metadata={"mode": self.mode})

    def prepare(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return noop_result("prepare", "vip prepare is handled by the legacy runc script")

    def switch(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return noop_result("switch", "vip switch is handled by the legacy runc script")

    def verify(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return noop_result("verify", "vip verification is handled by destination health checks")

    def script_env(self, config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        options = dict(self.plan.options or {})
        return {
            "TRAFFIC_MODE": self.mode,
            "VIP_ADDR": self.plan.vip_addr,
            "VIP_CIDR": self.plan.vip_cidr,
            "VIP_IF_SRC": (self.plan.interfaces or {}).get("source"),
            "VIP_IF_DST": (self.plan.interfaces or {}).get("dest"),
            "VIP_PORT": self.plan.port,
            "VIP_GARP_COUNT": options.get("vip_garp_count", 3),
            "VIP_GARP_INTERVAL_MS": options.get("vip_garp_interval_ms", 200),
            "VIP_GARP_MODE": options.get("vip_garp_mode", "A"),
            "VIP_CONNTRACK_CLEAR_SRC": _bool_int(options.get("vip_conntrack_clear_src", 0)),
        }


def _bool_int(value: Any) -> int:
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "on"} else 0
    return 1 if bool(value) else 0
