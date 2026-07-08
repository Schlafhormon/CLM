"""External traffic backend."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from clm.core.models import PreflightResult, TrafficPlan
from clm.host import HostExecutor
from clm.migration.traffic.base import TrafficActionResult, TrafficBackend, noop_result
from clm.migration.traffic.command import CommandTrafficBackend


class ExternalTrafficBackend(TrafficBackend):
    """Do not switch traffic inside CLM.

    A verify hook may be configured when CLM should check externally managed
    traffic after restore.
    """

    mode = "external"

    def __init__(
        self,
        plan: Optional[TrafficPlan] = None,
        *,
        executor: Optional[HostExecutor] = None,
        logger: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(plan=plan or TrafficPlan(mode=self.mode))
        self._verify_backend = CommandTrafficBackend(
            TrafficPlan(mode="command", hooks={"verify": (self.plan.hooks or {}).get("verify")}, options=self.plan.options),
            executor=executor,
            logger=logger,
        )

    def preflight(self, context: Optional[Mapping[str, Any]] = None) -> PreflightResult:
        verify_result = self._verify_backend.preflight(context)
        return PreflightResult(
            checks=(
                {"name": "traffic external selected", "ok": True, "detail": "CLM will not switch traffic"},
            )
            + tuple(check for check in verify_result.checks if check.get("name") == "traffic command verify"),
            blockers=verify_result.blockers,
            metadata={"mode": self.mode},
        )

    def prepare(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return noop_result("prepare", "external traffic prepare is managed outside CLM")

    def switch(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return noop_result("switch", "external traffic switch is managed outside CLM")

    def verify(self, context: Optional[Mapping[str, Any]] = None) -> TrafficActionResult:
        return self._verify_backend.verify(context)

    def script_env(self, config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        env: dict[str, Any] = {"TRAFFIC_MODE": self.mode}
        command_env = self._verify_backend.script_env(config)
        if "TRAFFIC_VERIFY_CMD" in command_env:
            env["TRAFFIC_VERIFY_CMD"] = command_env["TRAFFIC_VERIFY_CMD"]
        return env
