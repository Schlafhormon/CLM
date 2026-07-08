#!/usr/bin/env python3

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import clm.cli as cli
from clm.core import config as core_config
from clm.migration.strategies import (
    PostCopyStrategy,
    PreCopyStrategy,
    StopAndCopyStrategy,
    StrategySelectionError,
    canonical_strategy_name,
    select_strategy,
)


class StrategySelectionTests(unittest.TestCase):
    def test_manual_precopy_and_postcopy_selection(self):
        self.assertIsInstance(select_strategy(requested="precopy"), PreCopyStrategy)
        self.assertIsInstance(select_strategy(requested="pre-copy"), PreCopyStrategy)
        self.assertIsInstance(select_strategy(requested="postcopy"), PostCopyStrategy)
        self.assertIsInstance(select_strategy(requested="post-copy"), PostCopyStrategy)

    def test_auto_selection_uses_stop_and_copy_safe_default(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["migration"]["minimal_downtime"] = True

        strategy = select_strategy(cfg)

        self.assertIsInstance(strategy, StopAndCopyStrategy)
        self.assertEqual(strategy.name, "stop-and-copy")

    def test_auto_selection_allows_minimal_downtime_only_with_experimental_flag(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["migration"].pop("strategy", None)
        cfg["migration"]["minimal_downtime"] = True

        strategy = select_strategy(cfg, allow_experimental_minimal_downtime=True)

        self.assertIsInstance(strategy, PreCopyStrategy)
        self.assertEqual(strategy.name, "pre-copy")

    def test_auto_selection_accepts_config_experimental_minimal_downtime_flag(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["migration"].pop("strategy", None)
        cfg["migration"]["experimental_minimal_downtime"] = True

        strategy = select_strategy(cfg)

        self.assertIsInstance(strategy, PreCopyStrategy)
        self.assertEqual(strategy.name, "pre-copy")

    def test_explicit_config_strategy_overrides_auto_default(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["migration"]["strategy"] = "post-copy"

        strategy = select_strategy(cfg)

        self.assertIsInstance(strategy, PostCopyStrategy)

    def test_unknown_strategy_fails_fast(self):
        with self.assertRaises(StrategySelectionError):
            canonical_strategy_name("teleport")


class StrategyPlanAndAdapterTests(unittest.TestCase):
    def test_stop_and_copy_plan_is_dry_run_skeleton(self):
        cfg = deepcopy(cli.DEFAULTS)

        plan = select_strategy(requested="auto").plan(cfg)

        self.assertEqual(plan.request.strategy, "stop-and-copy")
        self.assertTrue(plan.dry_run)
        self.assertIn("stop source container", plan.steps)
        self.assertFalse(plan.artifacts["implemented"])

    def test_precopy_plan_documents_legacy_adapter(self):
        cfg = deepcopy(cli.DEFAULTS)

        plan = select_strategy(requested="precopy").plan(cfg)

        self.assertEqual(plan.request.strategy, "pre-copy")
        self.assertIn("legacy_method", plan.artifacts)
        self.assertIn("legacy", plan.warnings[0])

    def test_precopy_preflight_combines_runtime_and_strategy_checks(self):
        cfg = deepcopy(cli.DEFAULTS)

        result = select_strategy(requested="precopy").preflight(cfg)

        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["strategy"], "pre-copy")
        self.assertEqual(result.metadata["legacy_method"], "precopy")
        self.assertTrue(any(check["name"] == "strategy: pre-copy legacy adapter selected" for check in result.checks))

    def test_selection_accepts_migration_request(self):
        cfg = deepcopy(cli.DEFAULTS)
        request = core_config.legacy_env_to_migration_request(cfg, method="postcopy")

        strategy = select_strategy(request)

        self.assertIsInstance(strategy, PostCopyStrategy)

    def test_run_migration_reaches_legacy_strategy_adapter(self):
        cfg = deepcopy(cli.DEFAULTS)
        cfg["repo_path"] = "~/CLM"
        cfg["hosts"]["dest"]["user"] = "benke2"

        captured = {}

        def fake_run_remote(host, script, **kwargs):
            captured["host"] = host
            captured["script"] = script
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            migrate_log = Path(tmp) / "migrate" / "precopy.log"
            with patch("clm.cli.run_remote", side_effect=fake_run_remote):
                rc = cli.run_migration(
                    cfg,
                    method="precopy",
                    run_id="20260325_130000",
                    events_log="/mnt/criu/logs/mon-20260325_130000-events.ndjson",
                    migrate_log=str(migrate_log),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["host"], "benke1")
        self.assertIn("bash \"$REPO/scripts/migrate_precopy_vip_cutover.sh\"", captured["script"])


if __name__ == "__main__":
    unittest.main()
