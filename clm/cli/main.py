"""CLI parser and command dispatch."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from clm.cli import load_env
from clm.cli.commands import analyse, plots, preflight, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clm", description="Container Live Migration runner")
    parser.add_argument("-e", "--env", help="Pfad zur env.yaml", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)

    preflight.configure_parser(sub.add_parser("preflight", help="Preflight-Checks"))
    run.configure_parser(sub.add_parser("run", help="Run ausfuehren"))
    analyse.configure_parser(sub.add_parser("analyse", aliases=["analyze"], help="Batch oder Runs analysieren"))
    plots.configure_parser(sub.add_parser("plots", help="Plots fuer Batch oder Runs erzeugen"))

    return parser


def dispatch(args: argparse.Namespace, argv: Sequence[str] | None = None) -> int:
    env_path = getattr(args, "env", "config/env.yaml")
    cfg = load_env(env_path)

    if args.cmd == "preflight":
        return preflight.handle(args, cfg)
    if args.cmd == "run":
        return run.handle(args, cfg, env_path=env_path, argv=argv)
    if args.cmd in ("analyse", "analyze"):
        return analyse.handle(args, cfg)
    if args.cmd == "plots":
        return plots.handle(args, cfg)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch(args, argv=argv)
