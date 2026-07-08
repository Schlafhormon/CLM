"""Plan command adapter."""

from __future__ import annotations

import argparse


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-e", "--env", help="Pfad zur env.yaml", default=argparse.SUPPRESS)
    parser.add_argument(
        "--method",
        default="auto",
        choices=["auto", "stop-and-copy", "precopy", "postcopy"],
        help="Strategy/Method fuer den side-effect-free Plan",
    )


def handle(args: argparse.Namespace, cfg: dict) -> int:
    from clm.migration.strategies import select_strategy

    strategy = select_strategy(cfg, requested=args.method)
    plan = strategy.plan(cfg, dry_run=True)

    print("Migration plan:")
    print(f"- strategy: {plan.request.strategy}")
    print(f"- dry_run: {str(plan.dry_run).lower()}")
    if "implemented" in plan.artifacts:
        print(f"- executable: {str(bool(plan.artifacts['implemented'])).lower()}")
    elif "legacy_method" in plan.artifacts:
        print(f"- executable: true")
        print(f"- legacy_method: {plan.artifacts['legacy_method']}")
    for step in plan.steps:
        print(f"- step: {step}")
    for warning in plan.warnings:
        print(f"- warning: {warning}")
    return 0
