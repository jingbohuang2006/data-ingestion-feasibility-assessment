from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.models import NORMALIZED_FIELDS
from src.review_features import (
    FEATURE_COLUMNS,
    generate_review_features,
    load_feature_rules,
    read_normalized_reviews,
    write_feature_dataset,
)


ROOT = Path(__file__).parents[1]
RULES_PATH = ROOT / "config" / "review_feature_rules_v1.yaml"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "review_feature_cases.csv"


def test_feature_output_is_deterministic_and_preserves_order_and_rows() -> None:
    source = read_normalized_reviews(FIXTURE_PATH)
    rules = load_feature_rules(RULES_PATH)

    first = generate_review_features(source, rules)
    second = generate_review_features(source.copy(), rules)

    pd.testing.assert_frame_equal(first, second)
    assert list(first.columns) == FEATURE_COLUMNS
    assert len(first) == len(source)
    assert first["review_id"].tolist() == source["review_id"].tolist()
    assert first[NORMALIZED_FIELDS].fillna("").equals(source[NORMALIZED_FIELDS].fillna(""))


def test_text_unicode_whitespace_null_and_low_signal_rules() -> None:
    features = _features().set_index("review_id")

    assert features.loc["r1", "review_text_character_count"] == len("i cannot log in!")
    assert features.loc["r1", "review_text_word_count"] == 4
    assert features.loc["r2", "title_character_count"] == len("password trouble")
    assert features.loc["r5", "review_text_character_count"] == 0
    assert features.loc["r5", "review_text_word_count"] == 0
    assert not bool(features.loc["r5", "has_review_text"])
    assert not bool(features.loc["r5", "has_title"])
    assert bool(features.loc["r5", "missing_review_text"])
    assert bool(features.loc["r5", "missing_title"])
    assert bool(features.loc["r5", "low_signal_text"])
    assert len(features) == 6


def test_fixed_time_features_and_invalid_timestamp_handling() -> None:
    features = _features().set_index("review_id")

    assert features.loc["r1", "publication_year"] == 2026
    assert features.loc["r1", "publication_month"] == 7
    assert features.loc["r1", "publication_day_of_week"] == "Sunday"
    assert features.loc["r1", "review_age_days"] == 2.0
    assert features.loc["r1", "review_age_at_collection_days"] == 1.0
    assert features.loc["r2", "review_age_at_collection_days"] == pytest.approx(1 / 24)
    assert not bool(features.loc["r1", "publication_timestamp_missing_or_invalid"])
    assert pd.isna(features.loc["r3", "publication_year"])
    assert pd.isna(features.loc["r3", "review_age_days"])
    assert bool(features.loc["r3", "publication_timestamp_missing_or_invalid"])
    assert not bool(features.loc["r3", "missing_publication_timestamp"])
    assert bool(features.loc["r5", "missing_publication_timestamp"])
    assert features.loc["r4", "review_age_days"] == pytest.approx(1 / 3)
    assert features.loc["r6", "review_age_days"] == -1.0
    assert features.loc["r6", "review_age_at_collection_days"] == pytest.approx(1 / 48)


def test_repeated_body_ignores_title_and_full_content_requires_both() -> None:
    features = _features().set_index("review_id")

    assert bool(features.loc["r1", "repeated_review_body"])
    assert bool(features.loc["r2", "repeated_review_body"])
    assert features.loc["r1", "repeated_review_body_group_size"] == 2
    assert features.loc["r1", "repeated_review_body_fingerprint"] == features.loc["r2", "repeated_review_body_fingerprint"]
    assert not bool(features.loc["r1", "repeated_full_content"])
    assert not bool(features.loc["r2", "repeated_full_content"])
    assert not bool(features.loc["r5", "repeated_review_body"])
    assert len(features) == 6


def test_repeated_full_content_is_scoped_by_app_and_storefront() -> None:
    source = read_normalized_reviews(FIXTURE_PATH)
    copies = pd.concat([source.iloc[[0]], source.iloc[[0]], source.iloc[[0]]], ignore_index=True)
    copies["review_id"] = ["same-1", "same-2", "other-store"]
    copies.loc[2, "country"] = "gb"
    features = generate_review_features(copies, load_feature_rules(RULES_PATH)).set_index("review_id")

    assert bool(features.loc["same-1", "repeated_full_content"])
    assert features.loc["same-1", "repeated_full_content_group_size"] == 2
    assert not bool(features.loc["other-store", "repeated_full_content"])


def test_keyword_boundaries_phrases_language_and_metadata() -> None:
    features = _features().set_index("review_id")

    assert bool(features.loc["r1", "login_topic_signal"])
    assert bool(features.loc["r4", "payment_topic_signal"])
    assert bool(features.loc["r4", "customer_service_topic_signal"])
    assert bool(features.loc["r4", "delivery_topic_signal"])
    assert bool(features.loc["r3", "performance_topic_signal"])
    assert bool(features.loc["r1", "declared_language_available"])
    assert bool(features.loc["r1", "language_script_consistent"])
    assert not bool(features.loc["r6", "language_script_consistent"])
    assert not bool(features.loc["r1", "has_developer_reply"])
    assert bool(features.loc["r2", "has_developer_reply"])
    assert "quality_failure" not in features.columns


def test_keyword_token_boundary_does_not_match_substrings(tmp_path: Path) -> None:
    raw = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    raw["topic_signal_keywords"]["login"] = ["log"]
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    source = read_normalized_reviews(FIXTURE_PATH).iloc[[0]].copy()
    source.loc[source.index[0], "review_title"] = "Catalog"
    source.loc[source.index[0], "review_text"] = "Cataloging works"

    features = generate_review_features(source, load_feature_rules(path))

    assert not bool(features.iloc[0]["login_topic_signal"])


def test_rating_derived_sentiment_is_a_nullable_weak_label() -> None:
    features = _features().set_index("review_id")

    assert features.loc["r1", "weak_sentiment_label"] == "negative"
    assert features.loc["r2", "weak_sentiment_label"] == "negative"
    assert features.loc["r3", "weak_sentiment_label"] == "neutral"
    assert features.loc["r4", "weak_sentiment_label"] == "positive"
    assert features.loc["r6", "weak_sentiment_label"] == "positive"
    assert pd.isna(features.loc["r5", "weak_sentiment_label"])


def test_run_specific_output_does_not_overwrite_input(tmp_path: Path) -> None:
    input_copy = tmp_path / "normalized.csv"
    input_copy.write_bytes(FIXTURE_PATH.read_bytes())
    original = input_copy.read_bytes()

    csv_path, jsonl_path = write_feature_dataset(_features(), tmp_path / "features", "run-1")

    assert input_copy.read_bytes() == original
    assert csv_path.exists() and jsonl_path.exists()
    assert len(pd.read_csv(csv_path)) == 6
    with pytest.raises(FileExistsError, match="already exists"):
        write_feature_dataset(_features(), tmp_path / "features", "run-1")


def test_configuration_validation_is_actionable(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("rule_version: 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required sections"):
        load_feature_rules(path)


def _features() -> pd.DataFrame:
    return generate_review_features(read_normalized_reviews(FIXTURE_PATH), load_feature_rules(RULES_PATH))
