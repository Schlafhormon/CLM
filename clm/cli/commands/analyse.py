"""Analyse command adapter."""

from __future__ import annotations

import argparse


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-e", "--env", help="Pfad zur env.yaml", default=argparse.SUPPRESS)
    parser.add_argument("--batch", default="last", help="Batch-Selector: last | last:N | <batch-path>")
    parser.add_argument("--batch-manifest", help="Textdatei mit Batch-IDs oder Batch-Pfaden, eine Auswahl pro Zeile")
    parser.add_argument("--runs-dir", help="Explizites Runs-Verzeichnis (alternativ zu --batch)")
    parser.add_argument("--config", default="config/analysis.yaml", help="Analyse/Plot-Konfig (YAML/JSON)")
    parser.add_argument("--with-plots", action="store_true", help="Direkt nach Analyse auch Plots erzeugen")
    parser.add_argument("--combine-batches", action="store_true", help="Mehrere per --batch selektierte Batches gemeinsam auswerten")
    parser.add_argument(
        "--combined-output-dir",
        help="Output-Verzeichnis fuer gemeinsame Auswertung (Default: <runs_root>/analysis/combined_<selector>)",
    )
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--run-dir", help=argparse.SUPPRESS)


def handle(args: argparse.Namespace, cfg: dict) -> int:
    from clm import cli

    if getattr(args, "run_id", None) or getattr(args, "run_dir", None):
        return cli.analyze_single_run_cli(cfg, getattr(args, "run_id", None), getattr(args, "run_dir", None))
    if args.batch_manifest and args.batch and args.batch != "last":
        cli.die("--batch-manifest und --batch nicht gleichzeitig setzen")
    if args.runs_dir and args.batch and args.batch != "last":
        cli.die("--runs-dir und --batch nicht gleichzeitig setzen")
    return cli.analyse_cli(
        cfg,
        args.batch,
        args.runs_dir,
        args.config,
        args.with_plots,
        combine_batches=args.combine_batches,
        combined_output_dir=args.combined_output_dir,
        batch_manifest=args.batch_manifest,
    )
