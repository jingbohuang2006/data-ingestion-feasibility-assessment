"""Command-line entry point for the feasibility assessment."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from .amazon_probe import run_amazon_probe
from .apple_app_store_validation import run_apple_app_store_validation
from .apple_app_store_probe import run_apple_app_store_probe
from .comparison import build_app_store_comparison, build_comparison
from .config import load_config
from .google_play_probe import run_google_play_probe
from .models import ProbeResult
from .models import NORMALIZED_FIELDS
from .quality_checks import calculate_quality_metrics
from .report_generator import generate_app_store_reports, generate_reports
from .steam_probe import run_steam_probe


def main() -> int:
    """Run probes and generate reports."""
    parser = argparse.ArgumentParser(description="Run review-source feasibility assessment.")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML configuration.")
    parser.add_argument(
        "--source",
        choices=["all", "steam", "amazon", "app_stores", "google_play", "apple_app_store", "apple_app_store_validation"],
        default="all",
        help="Source to run.",
    )
    parser.add_argument("--offline-only", action="store_true", help="Do not perform live HTTP requests.")
    parser.add_argument("--skip-live-amazon", action="store_true", help="Skip live Amazon GET tests.")
    parser.add_argument("--report-only", action="store_true", help="Generate reports from empty/skipped probe results.")
    parser.add_argument("--validation-run-id", help="Optional output run ID for isolated Apple validation outputs.")
    parser.add_argument(
        "--validation-max-reviews",
        type=int,
        help="Optional temporary cap for Apple validation runs, useful for 500 or 1,000 row test runs.",
    )
    args = parser.parse_args()

    root = Path.cwd()
    _setup_logging(root)
    config = load_config(args.config)

    if args.source == "apple_app_store_validation":
        return _run_apple_validation(args, config, root)

    if args.source in {"app_stores", "google_play", "apple_app_store"}:
        return _run_app_store_assessment(args, config, root)

    results: dict[str, ProbeResult] = {}
    if args.report_only:
        results["steam"] = ProbeResult(source="steam", executed=False, skipped_reason="Report-only mode.")
        results["amazon"] = ProbeResult(source="amazon", executed=False, skipped_reason="Report-only mode.")
    else:
        if args.source in {"all", "steam"}:
            if args.offline_only:
                results["steam"] = ProbeResult(source="steam", executed=False, skipped_reason="Offline-only mode.")
            else:
                results["steam"] = run_steam_probe(config, root)
        else:
            results["steam"] = ProbeResult(source="steam", executed=False, skipped_reason="Source not selected.")

        if args.source in {"all", "amazon"}:
            results["amazon"] = run_amazon_probe(
                config,
                root,
                skip_live=args.skip_live_amazon,
                offline_only=args.offline_only,
            )
        else:
            results["amazon"] = ProbeResult(source="amazon", executed=False, skipped_reason="Source not selected.")

    quality_list = [calculate_quality_metrics(result) for result in results.values()]
    quality_by_source = {metrics["source"]: metrics for metrics in quality_list}
    comparison = build_comparison(results["amazon"], results["steam"], quality_by_source)
    network_available = any(result.requests for result in results.values()) if not args.offline_only else False
    _ensure_processed_outputs(root, results)
    generate_reports(config, root, results, quality_list, comparison, network_available)
    logging.info("Assessment complete. Reports written to %s", root / "reports")
    return 0


def _run_app_store_assessment(args: argparse.Namespace, config, root: Path) -> int:
    results: dict[str, ProbeResult] = {}
    if args.report_only:
        results["google_play"] = ProbeResult(source="google_play", executed=False, skipped_reason="Report-only mode.")
        results["apple_app_store"] = ProbeResult(
            source="apple_app_store", executed=False, skipped_reason="Report-only mode."
        )
    else:
        if args.source in {"app_stores", "google_play"}:
            results["google_play"] = run_google_play_probe(config, root)
        else:
            results["google_play"] = ProbeResult(source="google_play", executed=False, skipped_reason="Source not selected.")

        if args.source in {"app_stores", "apple_app_store"}:
            if args.offline_only:
                results["apple_app_store"] = ProbeResult(
                    source="apple_app_store", executed=False, skipped_reason="Offline-only mode."
                )
            else:
                results["apple_app_store"] = run_apple_app_store_probe(config, root)
        else:
            results["apple_app_store"] = ProbeResult(
                source="apple_app_store", executed=False, skipped_reason="Source not selected."
            )

    quality_list = [calculate_quality_metrics(result) for result in results.values()]
    quality_by_source = {metrics["source"]: metrics for metrics in quality_list}
    comparison = build_app_store_comparison(results, quality_by_source)
    network_available = any(result.requests for result in results.values()) if not args.offline_only else False
    _ensure_processed_outputs(root, results)
    generate_app_store_reports(config, root, results, quality_list, comparison, network_available)
    logging.info("App-store assessment complete. Reports written to %s", root / "reports")
    return 0


def _run_apple_validation(args: argparse.Namespace, config, root: Path) -> int:
    if args.offline_only:
        logging.info("Apple validation skipped in offline-only mode.")
        return 0
    result = run_apple_app_store_validation(
        config,
        root,
        run_id=args.validation_run_id,
        max_reviews=args.validation_max_reviews,
    )
    logging.info("Apple validation complete. Processed output written to %s", result.processed_dir)
    logging.info("Apple validation EDA written to %s", result.reports_dir)
    return 0


def _setup_logging(root: Path) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(logs / "assessment.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _ensure_processed_outputs(root: Path, results: dict[str, ProbeResult]) -> None:
    """Create honest empty processed outputs for sources that collected no rows."""
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    for source, result in results.items():
        csv_path = processed / f"{source}_reviews.csv"
        jsonl_path = processed / f"{source}_reviews.jsonl"
        if not csv_path.exists():
            pd.DataFrame([], columns=NORMALIZED_FIELDS).to_csv(csv_path, index=False)
        if not jsonl_path.exists():
            status = result.skipped_reason or f"no {source} reviews collected"
            jsonl_path.write_text(
                json.dumps({"status": status, "fields": NORMALIZED_FIELDS}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    raise SystemExit(main())
