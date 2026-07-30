"""Generate deterministic validation reports for a review feature dataset."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .review_features import ISSUE_CATEGORIES


LINEAGE_FIELDS = [
    "source",
    "app_name",
    "item_id",
    "package_id",
    "item_name",
    "review_id",
    "country",
    "language",
    "source_url",
    "collected_at",
    "raw_page_number",
    "raw_cursor",
]


def build_validation_report(features: pd.DataFrame, input_row_count: int | None = None) -> dict[str, Any]:
    """Build summary and tidy distributions using actual observed rows."""
    row_count = len(features)
    expected_input_rows = row_count if input_row_count is None else input_row_count
    missing_columns = [field for field in LINEAGE_FIELDS if field not in features]
    if missing_columns:
        raise ValueError(f"Feature dataset is missing lineage fields: {', '.join(missing_columns)}")

    identity_fields = ["source", "item_id", "country", "language", "review_id"]
    identities = features[identity_fields].fillna("").astype(str)
    unique_identities = int(len(identities.drop_duplicates()))
    summary = {
        "input_row_count": int(expected_input_rows),
        "output_row_count": int(row_count),
        "row_count_preserved": expected_input_rows == row_count,
        "unique_contextual_review_identity_count": unique_identities,
        "duplicate_contextual_identity_count": int(row_count - unique_identities),
        "lineage_fields_retained": all(field in features for field in LINEAGE_FIELDS),
        "lineage_fields": LINEAGE_FIELDS,
        "feature_rule_versions": sorted(features["feature_rule_version"].dropna().astype(str).unique().tolist()),
        "feature_reference_timestamps": sorted(
            features["feature_reference_timestamp"].dropna().astype(str).unique().tolist()
        ),
        "overall_rates": {
            field: _boolean_rate(features[field])
            for field in [
                "missing_title",
                "missing_review_text",
                "missing_rating",
                "missing_publication_timestamp",
                "publication_timestamp_missing_or_invalid",
                "has_developer_reply",
                "has_app_version",
                "low_signal_text",
                "repeated_text",
                *[f"issue_{category}" for category in ISSUE_CATEGORIES],
            ]
        },
    }

    distributions: list[dict[str, Any]] = []
    group_fields = ["app_name", "country", "language"]
    for keys, group in features.groupby(group_fields, dropna=False, sort=True):
        base = dict(zip(group_fields, keys))
        base["row_count"] = len(group)
        for field in (
            "review_text_character_count",
            "review_text_word_count",
            "title_character_count",
            "title_word_count",
        ):
            values = pd.to_numeric(group[field], errors="coerce")
            distributions.append(
                {
                    **base,
                    "metric": field,
                    "value": None,
                    "count": int(values.notna().sum()),
                    "rate": None,
                    "minimum": _json_number(values.min()),
                    "median": _json_number(values.median()),
                    "mean": _json_number(values.mean()),
                    "maximum": _json_number(values.max()),
                }
            )
        for field in (
            "missing_title",
            "missing_review_text",
            "missing_rating",
            "missing_publication_timestamp",
            "publication_timestamp_missing_or_invalid",
            "has_developer_reply",
            "has_app_version",
            "low_signal_text",
            "repeated_text",
            *[f"issue_{category}" for category in ISSUE_CATEGORIES],
        ):
            distributions.append(
                {
                    **base,
                    "metric": field,
                    "value": True,
                    "count": int(_as_bool(group[field]).sum()),
                    "rate": _boolean_rate(group[field]),
                    "minimum": None,
                    "median": None,
                    "mean": None,
                    "maximum": None,
                }
            )
        for rating, count in group["rating"].fillna("<missing>").astype(str).value_counts(sort=False).sort_index().items():
            distributions.append(
                {
                    **base,
                    "metric": "rating_distribution",
                    "value": rating,
                    "count": int(count),
                    "rate": float(count / len(group)) if len(group) else None,
                    "minimum": None,
                    "median": None,
                    "mean": None,
                    "maximum": None,
                }
            )
        years = pd.to_numeric(group["publication_year"], errors="coerce")
        distributions.append(
            {
                **base,
                "metric": "publication_time_coverage",
                "value": "valid",
                "count": int(years.notna().sum()),
                "rate": float(years.notna().mean()) if len(group) else None,
                "minimum": _json_number(years.min()),
                "median": _json_number(years.median()),
                "mean": _json_number(years.mean()),
                "maximum": _json_number(years.max()),
            }
        )
    return {"summary": summary, "distributions": pd.DataFrame(distributions)}


def write_validation_report(
    report: dict[str, Any], output_root: str | Path, run_id: str
) -> tuple[Path, Path, Path]:
    """Write JSON, Markdown, and CSV validation artifacts to a new run directory."""
    safe_run_id = _safe_run_id(run_id)
    output_dir = Path(output_root) / safe_run_id
    if output_dir.exists():
        raise FileExistsError(f"Validation report directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    summary_path = output_dir / "feature_validation_summary.json"
    report_path = output_dir / "feature_validation_report.md"
    distributions_path = output_dir / "feature_distributions.csv"
    summary = report["summary"]
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_markdown(summary, report["distributions"]), encoding="utf-8")
    report["distributions"].to_csv(distributions_path, index=False)
    return summary_path, report_path, distributions_path


def _render_markdown(summary: dict[str, Any], distributions: pd.DataFrame) -> str:
    rates = summary["overall_rates"]
    contexts = (
        distributions[["app_name", "country", "language", "row_count"]]
        .drop_duplicates()
        .sort_values(["app_name", "country", "language"], na_position="last")
    )
    lines = [
        "# Review Feature Validation Report",
        "",
        "This deterministic report uses observed rows; run names are not interpreted as row counts.",
        "",
        "## Row and lineage validation",
        "",
        f"- Input rows: {summary['input_row_count']}",
        f"- Output rows: {summary['output_row_count']}",
        f"- Row count preserved: {summary['row_count_preserved']}",
        f"- Unique contextual review identities: {summary['unique_contextual_review_identity_count']}",
        f"- Duplicate contextual identities: {summary['duplicate_contextual_identity_count']}",
        f"- Required lineage fields retained: {summary['lineage_fields_retained']}",
        "",
        "## Overall feature rates",
        "",
        "| Feature | Rate |",
        "|---|---:|",
    ]
    lines.extend(f"| `{field}` | {rate:.4%} |" for field, rate in rates.items())
    lines.extend(
        [
            "",
            "Developer-reply absence is metadata availability only and is not an automatic quality failure.",
            "",
            "## App and storefront coverage",
            "",
            "| App | Country | Language | Rows |",
            "|---|---|---|---:|",
        ]
    )
    for row in contexts.itertuples(index=False):
        lines.append(f"| {row.app_name} | {row.country} | {row.language} | {row.row_count} |")
    lines.extend(
        [
            "",
            "Detailed text, rating, timestamp, missingness, metadata, signal, and keyword distributions are in "
            "`feature_distributions.csv`.",
            "",
        ]
    )
    return "\n".join(lines)


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.fillna(False).map(lambda value: str(value).strip().casefold() == "true")


def _boolean_rate(series: pd.Series) -> float:
    return float(_as_bool(series).mean()) if len(series) else 0.0


def _json_number(value: Any) -> int | float | None:
    if pd.isna(value):
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _safe_run_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not safe:
        raise ValueError("run_id must not be empty.")
    return safe


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, help="Generated review feature CSV.")
    parser.add_argument("--input-row-count", type=int)
    parser.add_argument("--output-root", default="reports/review_features")
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    features = pd.read_csv(args.features)
    report = build_validation_report(features, args.input_row_count)
    paths = write_validation_report(report, args.output_root, args.run_id)
    print(json.dumps({"rows": len(features), "outputs": [str(path) for path in paths]}, indent=2))


if __name__ == "__main__":
    main()
