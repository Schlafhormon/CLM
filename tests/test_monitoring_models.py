#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from clm.monitoring import (
    ProbeResult,
    ProbeSpec,
    evaluate_app_readiness,
    parse_legacy_http_csv,
    parse_legacy_l4_csv,
    parse_probe_spec,
    parse_probe_specs,
)


class MonitoringProbeSpecTests(unittest.TestCase):
    def test_parse_http_tcp_and_command_probe_specs(self):
        specs = parse_probe_specs(
            [
                {
                    "name": "app-health",
                    "type": "http",
                    "url": "http://10.0.0.2:8080/health",
                    "expected_statuses": [200, 204],
                    "required": "true",
                    "interval_ms": "250",
                    "timeout_ms": "1000",
                },
                {
                    "name": "app-port",
                    "type": "l4",
                    "host": "10.0.0.2",
                    "port": "8080",
                },
                {
                    "name": "custom-ready",
                    "type": "command",
                    "command": ["curl", "-fsS", "http://10.0.0.2:8080/ready"],
                    "expected_exit_code": 0,
                },
            ]
        )

        self.assertEqual([spec.type for spec in specs], ["http", "tcp", "command"])
        self.assertEqual(specs[0].expected_statuses, (200, 204))
        self.assertTrue(specs[0].required)
        self.assertEqual(specs[0].interval_ms, 250)
        self.assertEqual(specs[1].port, 8080)
        self.assertEqual(specs[2].command, ("curl", "-fsS", "http://10.0.0.2:8080/ready"))

    def test_probe_spec_validation_fails_fast_for_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "requires url"):
            parse_probe_spec({"name": "bad-http", "type": "http"})
        with self.assertRaisesRegex(ValueError, "requires port"):
            parse_probe_spec({"name": "bad-tcp", "type": "tcp", "host": "127.0.0.1"})
        with self.assertRaisesRegex(ValueError, "requires command"):
            parse_probe_spec({"name": "bad-command", "type": "command"})


class MonitoringReadinessTests(unittest.TestCase):
    def test_required_app_readiness_failure_is_fatal(self):
        required = ProbeSpec.http("health", "http://app/health", required=True)
        optional = ProbeSpec.tcp("port", "app", 8080, required=False)
        result = evaluate_app_readiness(
            [required, optional],
            [
                ProbeResult(required, "failure", timestamp_ms=1000, http_status=503),
                ProbeResult(optional, "success", timestamp_ms=1000),
            ],
        )

        self.assertEqual(result.status, "not_ready")
        self.assertFalse(result.ready)
        self.assertTrue(result.fatal)
        self.assertEqual(result.failed_required, ("health",))

    def test_optional_app_readiness_failure_is_nonfatal_warning(self):
        optional = ProbeSpec.http("warmup", "http://app/ready", required=False)
        result = evaluate_app_readiness(
            [optional],
            [ProbeResult(optional, "failure", timestamp_ms=1000, http_status=503)],
        )

        self.assertEqual(result.status, "ready_with_warnings")
        self.assertTrue(result.ready)
        self.assertFalse(result.fatal)
        self.assertEqual(result.failed_optional, ("warmup",))

    def test_missing_required_readiness_result_is_not_ready(self):
        required = ProbeSpec.command("verify", ["test", "-f", "/tmp/ready"], required=True)
        result = evaluate_app_readiness([required], [])

        self.assertEqual(result.status, "not_ready")
        self.assertFalse(result.ready)
        self.assertTrue(result.fatal)
        self.assertEqual(result.missing_required, ("verify",))


class LegacyMonitorAdapterTests(unittest.TestCase):
    def test_legacy_http_and_l4_csv_parse_to_probe_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            http_path = tmp_path / "mon-http.csv"
            l4_path = tmp_path / "mon-l4.csv"
            http_path.write_text(
                "\n".join(
                    [
                        "ts_iso,ts_ms,target,status,rt_ms,ttfb_ms,headers_ms,dns_ms,tcp_ms,tls_ms,bytes,err,t_start_ms,t_end_ms",
                        "t,1000,vip,200,2.5,1,1,0,0,0,0,,990,1000",
                        "t,1100,vip,503,2.0,1,1,0,0,0,0,,1090,1100",
                    ]
                ),
                encoding="utf-8",
            )
            l4_path.write_text(
                "\n".join(
                    [
                        "ts_iso,ts_ms,target,host,port,state,t_start_ms,t_end_ms",
                        "t,1000,vip,10.0.0.1,8080,up,990,1000",
                        "t,1100,vip,10.0.0.1,8080,down,1090,1100",
                    ]
                ),
                encoding="utf-8",
            )

            http_results = parse_legacy_http_csv(http_path)
            l4_results = parse_legacy_l4_csv(l4_path)

        self.assertEqual([result.ok for result in http_results], [True, False])
        self.assertEqual(http_results[0].http_status, 200)
        self.assertEqual([result.ok for result in l4_results], [True, False])
        self.assertEqual(l4_results[0].probe.type, "tcp")


if __name__ == "__main__":
    unittest.main()
