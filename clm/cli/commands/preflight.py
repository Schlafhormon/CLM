"""Preflight command adapter."""

from __future__ import annotations

import argparse


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-e", "--env", help="Pfad zur env.yaml", default=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="nur Config parsen, keine Checks")


def handle(args: argparse.Namespace, cfg: dict) -> int:
    from clm import cli

    return cli.preflight(cfg, dry_run=args.dry_run)
