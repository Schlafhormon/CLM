#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from clm.analysis.summary import build_core_summary, summarize_run_dir
from clm.core.models import MigrationResult


class CoreSummaryTests(unittest.TestCase):
    def test_build_core_summary_extracts_operator_fields(self):
        summary = build_core_summary(
            {
                "status": "success",
                "start_ts": "2026-07-08T10:00:00Z",
                "end_ts": "2026-07-08T10:00:02.500Z",
                "vip_http_client_visible_total_down_ms": 125.0,
                "vip_l4_downtime_ms": 80,
                "errors": ["late cleanup warning"],
                "artifacts": {"summary": "/runs/1/summary.json"},
                "run_id": "run-1",
            }
        )

        self.assertEqual(summary.status, "ok")
        self.assertTrue(summary.ok)
        self.assertAlmostEqual(summary.duration_ms, 2500.0)
        self.assertAlmostEqual(summary.downtime_ms, 125.0)
        self.assertEqual(summary.downtime["vip_l4_downtime_ms"], 80.0)
        self.assertEqual(summary.errors, ("late cleanup warning",))
        self.assertEqual(summary.artifact_paths["summary"], "/runs/1/summary.json")
        self.assertEqual(summary.as_dict()["schema"], "clm.analysis.summary.v1")

    def test_summarize_run_dir_merges_status_summary_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "monitor").mkdir()
            (run_dir / "analysis").mkdir()
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "start_ts": "2026-07-08T10:00:00Z",
                        "end_ts": "2026-07-08T10:00:01Z",
                        "error": "restore failed",
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.json").write_text(
                json.dumps({"http_downtime_ms": 42, "message": "analyze note"}),
                encoding="utf-8",
            )
            (run_dir / "events.ndjson").write_text("", encoding="utf-8")

            summary = summarize_run_dir(run_dir)

            self.assertEqual(summary.status, "failed")
            self.assertFalse(summary.ok)
            self.assertAlmostEqual(summary.duration_ms, 1000.0)
            self.assertAlmostEqual(summary.downtime_ms, 42.0)
            self.assertIn("restore failed", summary.errors)
            self.assertIn("analyze note", summary.errors)
            self.assertEqual(Path(summary.artifact_paths["status"]), run_dir / "status.json")
            self.assertEqual(Path(summary.artifact_paths["summary"]), run_dir / "summary.json")
            self.assertEqual(Path(summary.artifact_paths["events"]), run_dir / "events.ndjson")
            self.assertEqual(Path(summary.artifact_paths["monitor"]), run_dir / "monitor")
            self.assertEqual(Path(summary.artifact_paths["analysis"]), run_dir / "analysis")

    def test_build_core_summary_accepts_migration_result(self):
        result = MigrationResult(
            migration_id="mig-1",
            status="error",
            timings={"duration_s": 1.25},
            downtime_ms=33,
            errors=("checkpoint failed",),
            artifacts={"events": "/runs/mig-1/events.ndjson"},
        )

        summary = build_core_summary(result)

        self.assertEqual(summary.status, "failed")
        self.assertAlmostEqual(summary.duration_ms, 1250.0)
        self.assertAlmostEqual(summary.downtime_ms, 33.0)
        self.assertEqual(summary.errors, ("checkpoint failed",))
        self.assertEqual(summary.artifact_paths["events"], "/runs/mig-1/events.ndjson")
        self.assertEqual(summary.source, "mig-1")


if __name__ == "__main__":
    unittest.main()
