"""Run command adapter."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-e", "--env", help="Pfad zur env.yaml", default=argparse.SUPPRESS)
    parser.add_argument("--method", required=True, choices=["precopy", "postcopy"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--load",
        action="append",
        default=None,
        help=(
            "Legacy-Forschungsloadprofil(e): idle|heavy|cpu|wrk1|wrk2|wrk3|download|upload|stream; "
            "ohne --load laeuft eine normale Migration ohne synthetische Last"
        ),
    )
    parser.add_argument("--no-monitor", action="store_true")
    parser.add_argument("--no-migrate", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true", help="Run-spezifische Checkpoint-Artefakte nach dem Lauf nicht loeschen")
    parser.add_argument("--analyse", "--analyze", action="store_true", dest="analyse", help="Batch nach Run analysieren + Plots erzeugen")
    parser.add_argument(
        "--analysis-config",
        default="config/analysis.yaml",
        help="Pfad zu Analyse/Plot-Konfig (YAML/JSON)",
    )


def handle(args: argparse.Namespace, cfg: dict, *, env_path: str, argv: Sequence[str] | None = None) -> int:
    from clm import cli

    raw_argv = sys.argv[1:] if argv is None else list(argv)
    return cli.run_cli(
        cfg,
        args.method,
        args.repeats,
        args.load,
        args.no_monitor,
        args.no_migrate,
        no_cleanup=args.no_cleanup,
        auto_analyse=args.analyse,
        analysis_config_path=args.analysis_config,
        env_path=env_path,
        cli_argv=raw_argv,
    )
