from __future__ import annotations

from pathlib import Path

from src.binary_sentiment_baseline import (
    ID_COLUMN,
    MODEL_B_FEATURES,
    PROHIBITED_MODEL_INPUTS,
    TARGET_COLUMN,
    assert_split_integrity,
    deterministic_group_split,
    diagnostic_frame,
    load_and_validate_datasets,
    normalize_review_text,
    prepare_modeling_population,
)


ROOT = Path(__file__).parents[1]
FEATURE_PATH = (
    ROOT / "data/processed/review_features/apple-large-feature-v2/review_features.csv"
)
AUDIT_PATH = (
    ROOT
    / "reports/review_features/apple-large-feature-v2/manual_validation_sample_annotated.csv"
)


def test_normalized_text_grouping_is_unicode_case_and_whitespace_stable() -> None:
    assert normalize_review_text("  Ｇreat\n APP  ") == "great app"
    assert normalize_review_text("Straße") == normalize_review_text("STRASSE")


def test_audit_exclusion_is_complete_and_includes_duplicate_text_rows() -> None:
    features, audit = load_and_validate_datasets(FEATURE_PATH, AUDIT_PATH)
    population, counts, audit_groups = prepare_modeling_population(features, audit)

    assert counts["initial_feature_rows"] == 6396
    assert counts["direct_audit_rows_excluded"] == 135
    assert counts["additional_audit_text_duplicate_rows_excluded"] == 19
    assert counts["rows_after_audit_group_exclusion"] == 6242
    assert counts["neutral_or_nonbinary_rows_excluded"] == 461
    assert counts["modeling_population_rows"] == 5781
    assert not set(population[ID_COLUMN]) & set(audit[ID_COLUMN])
    assert not set(population["normalized_text_group"]) & audit_groups
    assert set(population[TARGET_COLUMN]) == {"negative", "positive"}


def test_group_split_is_deterministic_and_integrity_checked() -> None:
    features, audit = load_and_validate_datasets(FEATURE_PATH, AUDIT_PATH)
    population, _, audit_groups = prepare_modeling_population(features, audit)
    first_train, first_test = deterministic_group_split(population)
    second_train, second_test = deterministic_group_split(population)

    assert first_train.tolist() == second_train.tolist()
    assert first_test.tolist() == second_test.tolist()
    assert_split_integrity(
        population, first_train, first_test, set(audit[ID_COLUMN]), audit_groups
    )


def test_model_b_features_are_eligible_and_manual_diagnostic_is_held_out() -> None:
    features, audit = load_and_validate_datasets(FEATURE_PATH, AUDIT_PATH)
    diagnostic, excluded = diagnostic_frame(features, audit)

    assert not set(MODEL_B_FEATURES) & PROHIBITED_MODEL_INPUTS
    assert len(diagnostic) == 88
    assert excluded == 47
    assert set(diagnostic["diagnostic_label"]) == {"negative", "positive"}
    assert set(diagnostic[ID_COLUMN]).issubset(set(audit[ID_COLUMN]))
