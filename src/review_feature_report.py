"""Generate deterministic validation reports for a review feature dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .review_features import TOPIC_CATEGORIES


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


def build_validation_report(
    features: pd.DataFrame, input_row_count: int | None = None, manual_sample_size: int = 135
) -> dict[str, Any]:
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
        "weak_sentiment_label_counts": {
            str(label): int(count)
            for label, count in features["weak_sentiment_label"].fillna("<missing>").value_counts().items()
        },
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
                "repeated_full_content",
                "repeated_review_body",
                *[f"{category}_topic_signal" for category in TOPIC_CATEGORIES],
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
            "review_age_days",
            "review_age_at_collection_days",
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
            "repeated_full_content",
            "repeated_review_body",
            *[f"{category}_topic_signal" for category in TOPIC_CATEGORIES],
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
    return {
        "summary": summary,
        "distributions": pd.DataFrame(distributions),
        "manual_sample": create_manual_validation_sample(features, manual_sample_size),
    }


def create_manual_validation_sample(features: pd.DataFrame, target_size: int = 135) -> pd.DataFrame:
    """Create a deterministic coverage-oriented annotation sample."""
    if target_size < 1:
        raise ValueError("manual sample size must be positive.")
    topic_fields = [f"{category}_topic_signal" for category in TOPIC_CATEGORIES]
    required = [
        "review_id", "app_name", "country", "rating", "weak_sentiment_label",
        "review_title", "review_text", "low_signal_text", "repeated_full_content",
        "repeated_review_body", *topic_fields,
    ]
    missing = [field for field in required if field not in features]
    if missing:
        raise ValueError(f"Feature dataset is missing manual-validation fields: {', '.join(missing)}")

    candidates = features.copy()
    candidates["_stable_rank"] = candidates.apply(
        lambda row: hashlib.sha256(
            "|".join(str(row.get(field, "")) for field in ("source", "app_name", "country", "review_id"))
            .encode("utf-8")
        ).hexdigest(),
        axis=1,
    )
    candidates = candidates.sort_values("_stable_rank")
    selected: list[Any] = []

    coverage_groups: list[tuple[str, pd.Series]] = []
    for field in ("weak_sentiment_label", "app_name", "country"):
        for value in candidates[field].dropna().unique():
            coverage_groups.append((f"{field}:{value}", candidates[field].eq(value)))
    for field in ("low_signal_text", "repeated_full_content", "repeated_review_body", *topic_fields):
        coverage_groups.append((field, _as_bool(candidates[field])))
    for _, mask in coverage_groups:
        available = candidates.loc[mask & ~candidates.index.isin(selected)]
        if not available.empty and len(selected) < min(target_size, len(candidates)):
            selected.append(available.index[0])

    sentiment_order = ["negative", "neutral", "positive"]
    while len(selected) < min(target_size, len(candidates)):
        added = False
        for sentiment in sentiment_order:
            available = candidates.loc[
                candidates["weak_sentiment_label"].eq(sentiment) & ~candidates.index.isin(selected)
            ]
            if not available.empty:
                selected.append(available.index[0])
                added = True
                if len(selected) >= min(target_size, len(candidates)):
                    break
        if not added:
            remaining = candidates.loc[~candidates.index.isin(selected)]
            if remaining.empty:
                break
            selected.append(remaining.index[0])

    sample = candidates.loc[selected].copy()
    sample.insert(0, "annotation_status", "pending")
    sample["human_sentiment"] = ""
    sample["sentiment_agreement"] = ""
    sample["mixed_or_unclear"] = ""
    sample["topic_signal_relevance"] = ""
    for prefix in ("repeated_full_content", "repeated_review_body"):
        peer_details = sample.apply(
            lambda row: _duplicate_peer_details(row, candidates, prefix), axis=1
        )
        sample[f"{prefix}_example_review_id"] = peer_details.map(lambda value: value[0])
        sample[f"{prefix}_example_title"] = peer_details.map(lambda value: value[1])
        sample[f"{prefix}_example_body"] = peer_details.map(lambda value: value[2])
    sample["full_content_duplication_judgment"] = ""
    sample["review_body_duplication_judgment"] = ""
    columns = [
        "annotation_status", "review_id", "app_name", "country", "rating",
        "weak_sentiment_label", "review_title", "review_text", "low_signal_text",
        "repeated_full_content", "repeated_review_body", *topic_fields,
        "repeated_full_content_example_review_id", "repeated_full_content_example_title",
        "repeated_full_content_example_body", "repeated_review_body_example_review_id",
        "repeated_review_body_example_title", "repeated_review_body_example_body",
        "human_sentiment", "sentiment_agreement", "mixed_or_unclear", "topic_signal_relevance",
        "full_content_duplication_judgment", "review_body_duplication_judgment",
    ]
    return sample.loc[:, columns].rename(columns={"app_name": "app", "country": "storefront"})


def _duplicate_peer_details(
    row: pd.Series, candidates: pd.DataFrame, prefix: str
) -> tuple[str, str, str]:
    """Return one same-scope peer for a flagged duplicate, or blank display values."""
    if not bool(row[prefix]):
        return "", "", ""
    fingerprint_field = f"{prefix}_fingerprint"
    app_fields = ("item_id", "package_id", "item_name", "app_name")
    app_field = next((field for field in app_fields if pd.notna(row.get(field)) and str(row.get(field)).strip()), None)
    app_value = str(row.get(app_field)).strip().casefold() if app_field else ""
    same_scope = (
        candidates[fingerprint_field].eq(row[fingerprint_field])
        & candidates["source"].fillna("").astype(str).str.strip().str.casefold().eq(
            str(row.get("source", "")).strip().casefold()
        )
        & candidates["country"].fillna("").astype(str).str.strip().str.casefold().eq(
            str(row.get("country", "")).strip().casefold()
        )
        & candidates["language"].fillna("").astype(str).str.strip().str.casefold().eq(
            str(row.get("language", "")).strip().casefold()
        )
        & candidates["review_id"].astype(str).ne(str(row["review_id"]))
    )
    if app_field:
        same_scope &= candidates[app_field].fillna("").astype(str).str.strip().str.casefold().eq(app_value)
    peers = candidates.loc[same_scope]
    if peers.empty:
        return "", "", ""
    peer = peers.iloc[0]
    return (
        str(peer.get("review_id", "")),
        str(peer.get("review_title", "")) if pd.notna(peer.get("review_title")) else "",
        str(peer.get("review_text", "")) if pd.notna(peer.get("review_text")) else "",
    )


def write_validation_report(
    report: dict[str, Any], output_root: str | Path, run_id: str
) -> tuple[Path, Path, Path, Path]:
    """Write JSON, Markdown, and CSV validation artifacts to a new run directory."""
    safe_run_id = _safe_run_id(run_id)
    output_dir = Path(output_root) / safe_run_id
    if output_dir.exists():
        raise FileExistsError(f"Validation report directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    summary_path = output_dir / "feature_validation_summary.json"
    report_path = output_dir / "feature_validation_report.md"
    distributions_path = output_dir / "feature_distributions.csv"
    manual_sample_path = output_dir / "manual_validation_sample.csv"
    summary = report["summary"]
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_render_markdown(summary, report["distributions"]), encoding="utf-8")
    report["distributions"].to_csv(distributions_path, index=False)
    report["manual_sample"].to_csv(manual_sample_path, index=False)
    return summary_path, report_path, distributions_path, manual_sample_path


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
            "## Weak sentiment label coverage",
            "",
            "These rating-derived counts describe sampling coverage only; they are not validated sentiment outcomes.",
            "",
            "| Weak label | Rows |",
            "|---|---:|",
            *[
                f"| `{label}` | {count} |"
                for label, count in summary["weak_sentiment_label_counts"].items()
            ],
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
            "Detailed text, age, rating, timestamp, missingness, metadata, and topic-signal distributions are in "
            "`feature_distributions.csv`.",
            "",
            "## Manual validation decisions",
            "",
            "Complete `manual_validation_sample.csv` before drawing baseline-usage conclusions. The sample is "
            "deterministic and coverage-oriented across weak sentiment, Apps, storefronts, low-signal text, "
            "both repeated-content flags, and all six topic signals.",
            "",
            "- Sentiment groups reliable enough for baseline usage: **Pending human annotation.** Compare "
            "`human_sentiment` with the rating-derived weak label by class; do not infer reliability from rating alone.",
            "- Feature rules requiring refinement: **Pending human annotation.** Review disagreements, "
            "`mixed_or_unclear`, repeated-content false positives, and topic relevance.",
            "- Topic-signal consistency across Apps: **Pending human annotation.** Compare relevance rates by App "
            "and signal; small cells must remain descriptive.",
            "",
            "`weak_sentiment_label` is a weak label for validation only. It must never be used as a model feature "
            "or as a prediction target in later modeling, and `rating` must not be used to validate it circularly.",
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
    parser.add_argument("--manual-sample-size", type=int, default=135)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    features = pd.read_csv(args.features)
    report = build_validation_report(features, args.input_row_count, args.manual_sample_size)
    paths = write_validation_report(report, args.output_root, args.run_id)
    print(json.dumps({"rows": len(features), "outputs": [str(path) for path in paths]}, indent=2))


if __name__ == "__main__":
    main()
