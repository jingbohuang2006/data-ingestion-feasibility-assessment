"""Deterministic, configuration-driven review feature generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .models import NORMALIZED_FIELDS


ISSUE_CATEGORIES = (
    "login",
    "payment",
    "performance",
    "subscription",
    "delivery",
    "customer_service",
)

DERIVED_FEATURE_FIELDS = [
    "publication_timestamp",
    "review_text_character_count",
    "review_text_word_count",
    "title_character_count",
    "title_word_count",
    "has_review_text",
    "has_title",
    "publication_year",
    "publication_month",
    "publication_day_of_week",
    "review_age_days",
    "publication_timestamp_missing_or_invalid",
    "has_app_version",
    "has_developer_reply",
    "low_signal_text",
    "repeated_text",
    "repeated_text_fingerprint",
    "repeated_text_group_size",
    "missing_title",
    "missing_review_text",
    "missing_rating",
    "missing_publication_timestamp",
    "declared_language_available",
    "language_script_consistent",
    *[f"issue_{category}" for category in ISSUE_CATEGORIES],
    "feature_rule_version",
    "feature_reference_timestamp",
]
FEATURE_COLUMNS = [*NORMALIZED_FIELDS, *DERIVED_FEATURE_FIELDS]


@dataclass(frozen=True)
class FeatureRules:
    """Validated feature rules and their original serializable configuration."""

    version: str
    reference_timestamp: datetime
    raw: dict[str, Any]
    word_pattern: re.Pattern[str]


def load_feature_rules(path: str | Path) -> FeatureRules:
    """Load and validate a versioned YAML feature-rule configuration."""
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"Feature-rule configuration does not exist: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Feature-rule configuration root must be a mapping.")

    required = {
        "rule_version",
        "reference_timestamp",
        "text_normalization",
        "word_count",
        "low_signal",
        "repeated_text",
        "missing_fields",
        "language_indicator",
        "keyword_categories",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"Feature-rule configuration is missing required sections: {', '.join(missing)}")

    version = str(raw["rule_version"]).strip()
    if not version:
        raise ValueError("rule_version must be a non-empty string.")
    reference = _parse_timestamp(raw["reference_timestamp"])
    if reference is None:
        raise ValueError("reference_timestamp must be a valid timezone-aware ISO-8601 timestamp.")

    normalization = raw["text_normalization"]
    if not isinstance(normalization, dict) or normalization.get("unicode_form") not in {"NFC", "NFKC"}:
        raise ValueError("text_normalization.unicode_form must be NFC or NFKC.")
    word_count = raw["word_count"]
    if not isinstance(word_count, dict) or not str(word_count.get("pattern", "")).strip():
        raise ValueError("word_count.pattern must be a non-empty regular expression.")
    try:
        word_pattern = re.compile(str(word_count["pattern"]), re.UNICODE)
    except re.error as exc:
        raise ValueError(f"word_count.pattern is invalid: {exc}") from exc

    low_signal = raw["low_signal"]
    for key in ("minimum_review_text_characters", "minimum_review_text_words"):
        if not isinstance(low_signal, dict) or not isinstance(low_signal.get(key), int) or low_signal[key] < 0:
            raise ValueError(f"low_signal.{key} must be a non-negative integer.")

    repeated = raw["repeated_text"]
    expected_scope = ["source", "app_identifier", "country", "language"]
    if not isinstance(repeated, dict) or repeated.get("scope") != expected_scope:
        raise ValueError(f"repeated_text.scope must be exactly {expected_scope}.")
    if repeated.get("fingerprint_algorithm") != "sha256":
        raise ValueError("repeated_text.fingerprint_algorithm must be sha256.")

    missing_fields = raw["missing_fields"]
    expected_missing_fields = ["review_title", "review_text", "rating", "review_date"]
    if not isinstance(missing_fields, dict) or missing_fields.get("fields") != expected_missing_fields:
        raise ValueError(f"missing_fields.fields must be exactly {expected_missing_fields}.")

    language_indicator = raw["language_indicator"]
    if not isinstance(language_indicator, dict):
        raise ValueError("language_indicator must be a mapping.")
    ratio = language_indicator.get("minimum_latin_letter_ratio")
    minimum_letters = language_indicator.get("minimum_letters")
    if not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
        raise ValueError("language_indicator.minimum_latin_letter_ratio must be between 0 and 1.")
    if not isinstance(minimum_letters, int) or minimum_letters < 1:
        raise ValueError("language_indicator.minimum_letters must be a positive integer.")

    keywords = raw["keyword_categories"]
    if not isinstance(keywords, dict):
        raise ValueError("keyword_categories must be a mapping.")
    missing_categories = [category for category in ISSUE_CATEGORIES if category not in keywords]
    if missing_categories:
        raise ValueError(f"keyword_categories is missing: {', '.join(missing_categories)}")
    for category in ISSUE_CATEGORIES:
        values = keywords[category]
        if not isinstance(values, list) or not values or any(not str(value).strip() for value in values):
            raise ValueError(f"keyword_categories.{category} must be a non-empty list of non-empty strings.")

    return FeatureRules(version, reference, raw, word_pattern)


def generate_review_features(frame: pd.DataFrame, rules: FeatureRules) -> pd.DataFrame:
    """Return exactly one stable feature row for every normalized input row."""
    missing_columns = [field for field in NORMALIZED_FIELDS if field not in frame.columns]
    if missing_columns:
        raise ValueError(f"Input is missing normalized review columns: {', '.join(missing_columns)}")

    source = frame.loc[:, NORMALIZED_FIELDS].copy()
    output = source.copy()
    review_text = source["review_text"].map(_original_or_none)
    title = source["review_title"].map(_original_or_none)
    normalized_review = review_text.map(lambda value: normalize_text(value, rules))
    normalized_title = title.map(lambda value: normalize_text(value, rules))

    output["publication_timestamp"] = source["review_date"]
    output["review_text_character_count"] = normalized_review.str.len().astype("int64")
    output["review_text_word_count"] = normalized_review.map(lambda value: len(rules.word_pattern.findall(value)))
    output["title_character_count"] = normalized_title.str.len().astype("int64")
    output["title_word_count"] = normalized_title.map(lambda value: len(rules.word_pattern.findall(value)))
    output["has_review_text"] = normalized_review.ne("")
    output["has_title"] = normalized_title.ne("")

    parsed_dates = [_parse_timestamp(value) for value in source["review_date"]]
    output["publication_year"] = pd.array(
        [value.year if value is not None else None for value in parsed_dates], dtype="Int64"
    )
    output["publication_month"] = pd.array(
        [value.month if value is not None else None for value in parsed_dates], dtype="Int64"
    )
    output["publication_day_of_week"] = [
        value.strftime("%A") if value is not None else None for value in parsed_dates
    ]
    output["review_age_days"] = pd.array(
        [
            (rules.reference_timestamp - value).total_seconds() / 86400 if value is not None else None
            for value in parsed_dates
        ],
        dtype="Float64",
    )
    invalid_timestamp = pd.Series([value is None for value in parsed_dates], index=source.index)
    output["publication_timestamp_missing_or_invalid"] = invalid_timestamp

    output["has_app_version"] = source["app_version"].map(_is_present)
    output["has_developer_reply"] = source["developer_response"].map(_is_present)
    output["missing_title"] = ~output["has_title"]
    output["missing_review_text"] = ~output["has_review_text"]
    output["missing_rating"] = source["rating"].map(lambda value: not _is_present(value))
    output["missing_publication_timestamp"] = source["review_date"].map(lambda value: not _is_present(value))
    output["declared_language_available"] = source["language"].map(_is_present)
    combined = (normalized_title + " " + normalized_review).str.strip()
    output["language_script_consistent"] = [
        _language_script_consistency(text, language, rules)
        for text, language in zip(combined, source["language"])
    ]

    low_signal = rules.raw["low_signal"]
    output["low_signal_text"] = (
        ~output["has_review_text"]
        | (output["review_text_character_count"] < low_signal["minimum_review_text_characters"])
        | (output["review_text_word_count"] < low_signal["minimum_review_text_words"])
    )

    repeated = rules.raw["repeated_text"]
    fingerprint_text = _fingerprint_text(normalized_title, normalized_review, repeated)
    minimum_length = int(repeated.get("minimum_normalized_characters", 1))
    fingerprints = fingerprint_text.map(
        lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest() if len(value) >= minimum_length else None
    )
    app_identifier = source.apply(_app_identifier, axis=1)
    scope = pd.DataFrame(
        {
            "source": source["source"].map(_scope_value),
            "app_identifier": app_identifier,
            "country": source["country"].map(_scope_value),
            "language": source["language"].map(_scope_value),
            "fingerprint": fingerprints,
        },
        index=source.index,
    )
    valid = scope["fingerprint"].notna()
    group_sizes = pd.Series(0, index=source.index, dtype="int64")
    group_sizes.loc[valid] = (
        scope.loc[valid]
        .groupby(["source", "app_identifier", "country", "language", "fingerprint"], dropna=False)[
            "fingerprint"
        ]
        .transform("size")
        .astype("int64")
    )
    output["repeated_text"] = group_sizes.gt(1)
    output["repeated_text_fingerprint"] = fingerprints
    output["repeated_text_group_size"] = group_sizes

    for category in ISSUE_CATEGORIES:
        patterns = [
            _keyword_pattern(normalize_text(keyword, rules))
            for keyword in rules.raw["keyword_categories"][category]
        ]
        output[f"issue_{category}"] = combined.map(
            lambda value: any(pattern.search(value) is not None for pattern in patterns)
        )

    output["feature_rule_version"] = rules.version
    output["feature_reference_timestamp"] = rules.reference_timestamp.isoformat().replace("+00:00", "Z")
    if len(output) != len(frame):
        raise RuntimeError("Feature generation changed the review row count.")
    return output.loc[:, FEATURE_COLUMNS]


def read_normalized_reviews(path: str | Path) -> pd.DataFrame:
    """Read normalized reviews without inventing values for missing text."""
    return pd.read_csv(Path(path), dtype=object, keep_default_na=False, na_values=[])


def write_feature_dataset(
    features: pd.DataFrame, output_root: str | Path, run_id: str
) -> tuple[Path, Path]:
    """Write CSV and JSONL into a new run-specific feature directory."""
    safe_run_id = _safe_run_id(run_id)
    output_dir = Path(output_root) / safe_run_id
    if output_dir.exists():
        raise FileExistsError(f"Feature output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    csv_path = output_dir / "review_features.csv"
    jsonl_path = output_dir / "review_features.jsonl"
    features.to_csv(csv_path, index=False)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in features.astype(object).where(pd.notna(features), None).to_dict(orient="records"):
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return csv_path, jsonl_path


def normalize_text(value: Any, rules: FeatureRules) -> str:
    """Normalize text for matching and derived calculations, never storage."""
    if not _is_present(value):
        return ""
    settings = rules.raw["text_normalization"]
    text = unicodedata.normalize(settings["unicode_form"], str(value))
    if settings.get("casefold", True):
        text = text.casefold()
    if settings.get("collapse_whitespace", True):
        text = " ".join(text.split())
    if settings.get("trim", True):
        text = text.strip()
    return text


def _parse_timestamp(value: Any) -> datetime | None:
    if not _is_present(value):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _is_present(value: Any) -> bool:
    return value is not None and not pd.isna(value) and bool(str(value).strip())


def _original_or_none(value: Any) -> Any:
    return value if _is_present(value) else None


def _scope_value(value: Any) -> str:
    return str(value).strip().casefold() if _is_present(value) else ""


def _app_identifier(row: pd.Series) -> str:
    for field in ("item_id", "package_id", "item_name", "app_name"):
        if _is_present(row[field]):
            return f"{field}:{_scope_value(row[field])}"
    return ""


def _fingerprint_text(title: pd.Series, review: pd.Series, rules: dict[str, Any]) -> pd.Series:
    parts: list[pd.Series] = []
    if rules.get("include_title", True):
        parts.append(title)
    if rules.get("include_review_text", True):
        parts.append(review)
    if not parts:
        raise ValueError("repeated_text must include title and/or review text.")
    result = parts[0]
    for part in parts[1:]:
        result = result + "\n" + part
    return result.str.strip()


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.UNICODE)


def _language_script_consistency(text: str, declared_language: Any, rules: FeatureRules) -> bool | None:
    settings = rules.raw["language_indicator"]
    if not settings.get("enabled", True) or not _is_present(declared_language):
        return None
    language = str(declared_language).strip().casefold().split("-", 1)[0]
    if language not in settings["supported_declared_languages"]:
        return None
    letters = [character for character in text if character.isalpha()]
    if len(letters) < int(settings["minimum_letters"]):
        return None
    latin = sum("LATIN" in unicodedata.name(character, "") for character in letters)
    return latin / len(letters) >= float(settings["minimum_latin_letter_ratio"])


def _safe_run_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not safe:
        raise ValueError("run_id must contain at least one letter, digit, dot, underscore, or hyphen.")
    return safe


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Normalized review CSV path.")
    parser.add_argument("--config", required=True, help="Versioned feature-rule YAML path.")
    parser.add_argument("--output-root", default="data/processed/review_features")
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    rules = load_feature_rules(args.config)
    features = generate_review_features(read_normalized_reviews(args.input), rules)
    csv_path, jsonl_path = write_feature_dataset(features, args.output_root, args.run_id)
    print(json.dumps({"rows": len(features), "csv": str(csv_path), "jsonl": str(jsonl_path)}, indent=2))


if __name__ == "__main__":
    main()
