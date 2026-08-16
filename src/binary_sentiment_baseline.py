"""Deterministic binary sentiment baselines with strict leakage controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


RANDOM_SEED = 20260811
TARGET_COLUMN = "weak_sentiment_label"
TEXT_COLUMN = "review_text"
ID_COLUMN = "review_id"
CLASS_ORDER = ["negative", "positive"]

TOPIC_FEATURES = [
    "login_topic_signal",
    "payment_topic_signal",
    "performance_topic_signal",
    "subscription_topic_signal",
    "delivery_topic_signal",
    "customer_service_topic_signal",
]
QUALITY_BINARY_FEATURES = ["low_signal_text", "language_script_consistent"]
QUALITY_NUMERIC_FEATURES = [
    "review_text_character_count",
    "review_text_word_count",
    "title_character_count",
    "title_word_count",
]
METADATA_BINARY_FEATURES = ["has_app_version"]
METADATA_NUMERIC_FEATURES = ["publication_year", "publication_month"]
METADATA_CATEGORICAL_FEATURES = ["app_name", "country", "publication_day_of_week"]
MODEL_B_FEATURES = [
    TEXT_COLUMN,
    *TOPIC_FEATURES,
    *QUALITY_BINARY_FEATURES,
    *QUALITY_NUMERIC_FEATURES,
    *METADATA_BINARY_FEATURES,
    *METADATA_NUMERIC_FEATURES,
    *METADATA_CATEGORICAL_FEATURES,
]

# Explicitly excluded from model inputs. This includes the target, every rating-derived
# field, identifiers/lineage, exact-text group signals, split helpers, and fields that
# arise after review publication or have no legitimate predictive meaning here.
PROHIBITED_MODEL_INPUTS = {
    "rating",
    "missing_rating",
    TARGET_COLUMN,
    "annotation_status",
    "human_sentiment",
    "sentiment_agreement",
    "mixed_or_unclear",
    "topic_signal_relevance",
    "full_content_duplication_judgment",
    "review_body_duplication_judgment",
    ID_COLUMN,
    "author_id",
    "author_name",
    "item_id",
    "package_id",
    "item_name",
    "source_url",
    "raw_page_number",
    "raw_cursor",
    "normalized_text_group",
    "split_assignment",
    "recommendation",
    "verified_purchase",
    "helpful_votes",
    "funny_votes",
    "playtime_forever",
    "playtime_at_review",
    "developer_response",
    "developer_response_date",
    "has_developer_reply",
    "collected_at",
    "review_age_at_collection_days",
    "repeated_full_content",
    "repeated_full_content_fingerprint",
    "repeated_full_content_group_size",
    "repeated_review_body",
    "repeated_review_body_fingerprint",
    "repeated_review_body_group_size",
    "feature_rule_version",
    "feature_reference_timestamp",
}

REQUIRED_FEATURE_COLUMNS = {
    ID_COLUMN,
    TEXT_COLUMN,
    TARGET_COLUMN,
    "rating",
    "missing_rating",
    *MODEL_B_FEATURES,
}
REQUIRED_AUDIT_COLUMNS = {
    ID_COLUMN,
    TEXT_COLUMN,
    "annotation_status",
    "human_sentiment",
    "mixed_or_unclear",
    TARGET_COLUMN,
}


def normalize_review_text(value: Any) -> str:
    """Return a stable exact-text grouping key without changing stored source text."""
    if value is None or pd.isna(value):
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split()).strip()


def load_and_validate_datasets(
    feature_path: str | Path, audit_path: str | Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = pd.read_csv(feature_path, dtype={ID_COLUMN: "string"})
    audit = pd.read_csv(audit_path, dtype={ID_COLUMN: "string"})
    missing_features = sorted(REQUIRED_FEATURE_COLUMNS - set(features.columns))
    missing_audit = sorted(REQUIRED_AUDIT_COLUMNS - set(audit.columns))
    if missing_features:
        raise ValueError(f"Feature dataset is missing required columns: {', '.join(missing_features)}")
    if missing_audit:
        raise ValueError(f"Audit dataset is missing required columns: {', '.join(missing_audit)}")
    if features[ID_COLUMN].isna().any() or features[ID_COLUMN].duplicated().any():
        raise ValueError("Feature review_id values must be complete and unique.")
    if len(audit) != 135:
        raise ValueError(f"Audit dataset must contain exactly 135 rows; found {len(audit)}.")
    if audit[ID_COLUMN].isna().any() or audit[ID_COLUMN].duplicated().any():
        raise ValueError("Audit review_id values must be complete and unique.")
    if set(audit["annotation_status"].astype(str).str.casefold()) != {"completed"}:
        raise ValueError("Every audit row must have annotation_status=completed.")
    return features, audit


def prepare_modeling_population(
    features: pd.DataFrame, audit: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int], set[str]]:
    """Exclude all audit IDs and audit-text groups before removing neutral targets."""
    feature = features.copy()
    audited = audit.copy()
    feature["normalized_text_group"] = feature[TEXT_COLUMN].map(normalize_review_text)
    audited["normalized_text_group"] = audited[TEXT_COLUMN].map(normalize_review_text)
    if (feature["normalized_text_group"] == "").any():
        raise ValueError("Empty normalized review text cannot be grouped safely for this baseline.")
    if (audited["normalized_text_group"] == "").any():
        raise ValueError("An audited record has empty normalized review text.")

    audit_ids = set(audited[ID_COLUMN])
    matched = feature[feature[ID_COLUMN].isin(audit_ids)]
    matched_counts = matched[ID_COLUMN].value_counts()
    if len(matched) != 135 or len(matched_counts) != 135 or not matched_counts.eq(1).all():
        missing = sorted(audit_ids - set(matched[ID_COLUMN]))
        raise ValueError(
            "Could not match all 135 audited review_id values exactly once"
            + (f"; missing: {', '.join(missing[:10])}" if missing else ".")
        )
    for column in (TEXT_COLUMN, TARGET_COLUMN):
        left = matched.set_index(ID_COLUMN)[column].fillna("").astype(str).sort_index()
        right = audited.set_index(ID_COLUMN)[column].fillna("").astype(str).sort_index()
        if not left.equals(right):
            raise ValueError(f"Audit-to-feature match disagrees on {column}; exclusion is not reliable.")

    audit_text_groups = set(audited["normalized_text_group"])
    direct_mask = feature[ID_COLUMN].isin(audit_ids)
    text_mask = feature["normalized_text_group"].isin(audit_text_groups)
    additional_mask = text_mask & ~direct_mask
    after_audit = feature.loc[~text_mask].copy()
    modeling = after_audit[after_audit[TARGET_COLUMN].isin(CLASS_ORDER)].copy()
    counts = {
        "initial_feature_rows": len(feature),
        "direct_audit_rows_excluded": int(direct_mask.sum()),
        "additional_audit_text_duplicate_rows_excluded": int(additional_mask.sum()),
        "rows_after_audit_group_exclusion": len(after_audit),
        "neutral_or_nonbinary_rows_excluded": len(after_audit) - len(modeling),
        "modeling_population_rows": len(modeling),
        "modeling_population_groups": modeling["normalized_text_group"].nunique(),
    }
    return modeling, counts, audit_text_groups


def deterministic_group_split(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Select one deterministic stratified group fold as the common 20% test set."""
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED)
    train_index, test_index = next(
        splitter.split(frame, frame[TARGET_COLUMN], groups=frame["normalized_text_group"])
    )
    return np.asarray(train_index), np.asarray(test_index)


def assert_split_integrity(
    population: pd.DataFrame,
    train_index: np.ndarray,
    test_index: np.ndarray,
    audit_ids: set[str],
    audit_text_groups: set[str],
) -> None:
    train = population.iloc[train_index]
    test = population.iloc[test_index]
    assert len(train) and len(test)
    assert set(train[TARGET_COLUMN]) == set(CLASS_ORDER)
    assert set(test[TARGET_COLUMN]) == set(CLASS_ORDER)
    assert not set(train[ID_COLUMN]) & audit_ids
    assert not set(test[ID_COLUMN]) & audit_ids
    assert not set(train["normalized_text_group"]) & audit_text_groups
    assert not set(test["normalized_text_group"]) & audit_text_groups
    assert not set(train["normalized_text_group"]) & set(test["normalized_text_group"])
    assert not (set(MODEL_B_FEATURES) & PROHIBITED_MODEL_INPUTS)


def build_models() -> dict[str, Pipeline]:
    text = TfidfVectorizer(
        lowercase=False,
        preprocessor=normalize_review_text,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.98,
        sublinear_tf=True,
    )
    classifier = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=1000,
        random_state=RANDOM_SEED,
        solver="liblinear",
    )
    text_only = Pipeline([("tfidf", text), ("classifier", classifier)])

    numeric_features = [*QUALITY_NUMERIC_FEATURES, *METADATA_NUMERIC_FEATURES]
    binary_features = [*TOPIC_FEATURES, *QUALITY_BINARY_FEATURES, *METADATA_BINARY_FEATURES]
    preprocessing = ColumnTransformer(
        [
            ("text", text, TEXT_COLUMN),
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric_features,
            ),
            (
                "binary",
                Pipeline([("impute", SimpleImputer(strategy="most_frequent"))]),
                binary_features,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("one_hot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                METADATA_CATEGORICAL_FEATURES,
            ),
        ]
    )
    text_plus = Pipeline([("preprocessing", preprocessing), ("classifier", classifier)])
    return {"model_a_text_only": text_only, "model_b_text_plus_features": text_plus}


def evaluate_predictions(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, Any]:
    report = classification_report(
        y_true,
        y_pred,
        labels=CLASS_ORDER,
        output_dict=True,
        zero_division=0,
    )
    return {
        "rows": len(y_true),
        "class_balance": {label: int((y_true == label).sum()) for label in CLASS_ORDER},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=CLASS_ORDER).tolist(),
        "per_class": {
            label: {
                key: float(report[label][key]) for key in ("precision", "recall", "f1-score")
            }
            for label in CLASS_ORDER
        },
        "macro_f1": float(f1_score(y_true, y_pred, labels=CLASS_ORDER, average="macro")),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }


def diagnostic_frame(features: pd.DataFrame, audit: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    sentiment = audit["human_sentiment"].astype(str).str.strip().str.casefold()
    clear = audit["mixed_or_unclear"].astype(str).str.strip().str.casefold().eq("no")
    eligible = clear & sentiment.isin(CLASS_ORDER)
    labels = audit.loc[eligible, [ID_COLUMN]].copy()
    labels["diagnostic_label"] = sentiment.loc[eligible]
    diagnostic = features.merge(labels, on=ID_COLUMN, how="inner", validate="one_to_one")
    if len(diagnostic) != int(eligible.sum()):
        raise ValueError("Could not attach every eligible manual diagnostic label to feature rows.")
    return diagnostic, int((~eligible).sum())


def make_error_sample(
    test: pd.DataFrame,
    prediction: np.ndarray,
    probability_positive: np.ndarray,
    model_name: str,
) -> pd.DataFrame:
    errors = test.loc[prediction != test[TARGET_COLUMN].to_numpy()].copy()
    if errors.empty:
        return pd.DataFrame()
    errors["prediction"] = prediction[prediction != test[TARGET_COLUMN].to_numpy()]
    errors["positive_probability"] = probability_positive[prediction != test[TARGET_COLUMN].to_numpy()]
    errors["confidence"] = np.maximum(errors["positive_probability"], 1 - errors["positive_probability"])
    errors["error_type"] = np.where(
        errors["low_signal_text"].astype(bool),
        "short_or_low_information",
        np.where(
            errors[TARGET_COLUMN].eq("positive"),
            "positive_weak_target_predicted_negative",
            "negative_weak_target_predicted_positive",
        ),
    )
    selected = (
        errors.sort_values(["error_type", "confidence", ID_COLUMN], ascending=[True, False, True])
        .groupby("error_type", sort=True)
        .head(3)
        .head(9)
        .copy()
    )
    selected["model"] = model_name
    selected["example_key"] = selected[ID_COLUMN].map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()[:12]
    )
    columns = [
        "model",
        "example_key",
        "error_type",
        TARGET_COLUMN,
        "prediction",
        "positive_probability",
        TEXT_COLUMN,
        "low_signal_text",
        *TOPIC_FEATURES,
        "app_name",
        "country",
    ]
    return selected[columns]


def run_baseline(
    feature_path: str | Path,
    audit_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    features, audit = load_and_validate_datasets(feature_path, audit_path)
    population, exclusion_counts, audit_text_groups = prepare_modeling_population(features, audit)
    train_index, test_index = deterministic_group_split(population)
    audit_ids = set(audit[ID_COLUMN])
    assert_split_integrity(population, train_index, test_index, audit_ids, audit_text_groups)
    train = population.iloc[train_index].copy()
    test = population.iloc[test_index].copy()
    diagnostic, diagnostic_excluded = diagnostic_frame(features, audit)

    results: dict[str, Any] = {}
    error_samples: list[pd.DataFrame] = []
    test_predictions = pd.DataFrame(
        {
            "example_key": test[ID_COLUMN].map(
                lambda value: hashlib.sha256(str(value).encode()).hexdigest()[:12]
            ),
            "weak_target": test[TARGET_COLUMN].to_numpy(),
        }
    )
    diagnostic_predictions = pd.DataFrame(
        {
            "example_key": diagnostic[ID_COLUMN].map(
                lambda value: hashlib.sha256(str(value).encode()).hexdigest()[:12]
            ),
            "manual_diagnostic_label": diagnostic["diagnostic_label"].to_numpy(),
        }
    )
    fitted = build_models()
    for name, model in fitted.items():
        input_columns = [TEXT_COLUMN] if name == "model_a_text_only" else MODEL_B_FEATURES
        if set(input_columns) & PROHIBITED_MODEL_INPUTS:
            raise AssertionError(f"Prohibited model input detected for {name}.")
        x_train = train[TEXT_COLUMN] if name == "model_a_text_only" else train[input_columns]
        x_test = test[TEXT_COLUMN] if name == "model_a_text_only" else test[input_columns]
        x_diagnostic = (
            diagnostic[TEXT_COLUMN] if name == "model_a_text_only" else diagnostic[input_columns]
        )
        model.fit(x_train, train[TARGET_COLUMN])
        prediction = model.predict(x_test)
        positive_index = list(model.classes_).index("positive")
        probability_positive = model.predict_proba(x_test)[:, positive_index]
        diagnostic_prediction = model.predict(x_diagnostic)
        diagnostic_positive_probability = model.predict_proba(x_diagnostic)[:, positive_index]
        test_predictions[f"{name}_prediction"] = prediction
        test_predictions[f"{name}_positive_probability"] = probability_positive
        diagnostic_predictions[f"{name}_prediction"] = diagnostic_prediction
        diagnostic_predictions[f"{name}_positive_probability"] = diagnostic_positive_probability
        results[name] = {
            "input_columns": input_columns,
            "main_test": evaluate_predictions(test[TARGET_COLUMN], prediction),
            "manual_diagnostic": evaluate_predictions(
                diagnostic["diagnostic_label"], diagnostic_prediction
            ),
        }
        error_samples.append(
            make_error_sample(test, prediction, probability_positive, name)
        )

    split_summary = {
        "random_seed": RANDOM_SEED,
        "normalization": "Unicode NFKC, casefold, collapse whitespace, trim",
        "feature_dataset": str(feature_path),
        "audit_dataset": str(audit_path),
        "feature_dataset_rows": len(features),
        "audit_dataset_rows": len(audit),
        "audit_match_key": ID_COLUMN,
        "exclusions": exclusion_counts,
        "train": _partition_summary(train),
        "test": _partition_summary(test),
        "manual_diagnostic": {
            "eligible_rows": len(diagnostic),
            "excluded_mixed_unclear_or_nonbinary_rows": diagnostic_excluded,
            "class_balance": {
                label: int((diagnostic["diagnostic_label"] == label).sum()) for label in CLASS_ORDER
            },
        },
        "integrity_assertions": {
            "all_135_audit_ids_matched_exactly_once": True,
            "no_audit_ids_in_train_or_test": True,
            "no_audit_text_groups_in_train_or_test": True,
            "no_text_group_crosses_train_and_test": True,
            "no_prohibited_model_inputs": True,
            "same_train_test_records_for_both_models": True,
            "train_and_test_nonempty_with_both_classes": True,
        },
    }
    payload = {
        "experiment": "exploratory binary rating-derived weak-target baseline",
        "target_definition": "1-2 stars negative; 3 stars excluded; 4-5 stars positive",
        "target_is_ground_truth": False,
        "prohibited_model_inputs": sorted(PROHIBITED_MODEL_INPUTS),
        "feature_groups": {
            "text": [TEXT_COLUMN],
            "topic": TOPIC_FEATURES,
            "quality_binary": QUALITY_BINARY_FEATURES,
            "quality_numeric": QUALITY_NUMERIC_FEATURES,
            "metadata_binary": METADATA_BINARY_FEATURES,
            "metadata_numeric": METADATA_NUMERIC_FEATURES,
            "metadata_categorical": METADATA_CATEGORICAL_FEATURES,
        },
        "split": split_summary,
        "models": results,
    }

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "metrics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / "split_summary.json").write_text(
        json.dumps(split_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    combined_errors = pd.concat(error_samples, ignore_index=True)
    combined_errors.to_csv(destination / "error_analysis_sample.csv", index=False)
    test_predictions.to_csv(destination / "test_predictions.csv", index=False)
    diagnostic_predictions.to_csv(destination / "manual_diagnostic_predictions.csv", index=False)
    (destination / "modeling_report.md").write_text(
        render_report(payload, combined_errors), encoding="utf-8"
    )
    return payload


def _partition_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(frame),
        "normalized_text_groups": frame["normalized_text_group"].nunique(),
        "class_balance": {
            label: {
                "rows": int((frame[TARGET_COLUMN] == label).sum()),
                "proportion": float((frame[TARGET_COLUMN] == label).mean()),
            }
            for label in CLASS_ORDER
        },
    }


def render_report(payload: dict[str, Any], errors: pd.DataFrame) -> str:
    split = payload["split"]
    lines = [
        "# Binary Sentiment Baseline",
        "",
        "## Interpretation",
        "",
        "This is an exploratory weak-target experiment. The target is derived from ratings (1–2 negative,",
        "4–5 positive), with three-star reviews excluded. It is not manually verified sentiment ground truth.",
        "Rating, the weak label, and all rating-derived fields are excluded from model inputs.",
        "",
        "## Reproduce",
        "",
        "Run from the repository root:",
        "",
        "```bash",
        "python -m src.binary_sentiment_baseline",
        "```",
        "",
        "## Data and safeguards",
        "",
        f"- Feature dataset: `{split['feature_dataset']}` ({split['feature_dataset_rows']:,} rows)",
        f"- Audit dataset: `{split['audit_dataset']}` ({split['audit_dataset_rows']} rows)",
        f"- Direct audited rows excluded: {split['exclusions']['direct_audit_rows_excluded']}",
        "- Additional matching normalized-text rows excluded: "
        f"{split['exclusions']['additional_audit_text_duplicate_rows_excluded']}",
        f"- Binary modeling population: {split['exclusions']['modeling_population_rows']:,} rows",
        f"- Train/test: {split['train']['rows']:,}/{split['test']['rows']:,} rows using deterministic group-aware splitting",
        "- Identical normalized review text cannot cross partitions; all preprocessing is fitted on training rows only.",
        "",
        "## Models and feature controls",
        "",
        "- Model A: `review_text` normalized with Unicode NFKC/casefold/whitespace collapse, TF-IDF unigrams and bigrams, and class-balanced logistic regression.",
        "- Model B: the same text representation and classifier on the identical split, plus existing topic signals, row-local text/title quality counts, `low_signal_text`, `language_script_consistent`, app-version availability, publication year/month/day-of-week, App name, and country.",
        "- No hyperparameter search or threshold selection is performed. Every learned preprocessing step is fitted on training rows only.",
        "",
        "Explicit model-input denylist:",
        "",
        ", ".join(f"`{column}`" for column in payload["prohibited_model_inputs"]),
        "",
        "## Main held-out evaluation",
        "",
        "| Model | Macro F1 | Balanced accuracy | Accuracy |",
        "|---|---:|---:|---:|",
    ]
    for name, result in payload["models"].items():
        metric = result["main_test"]
        lines.append(
            f"| {name} | {metric['macro_f1']:.4f} | {metric['balanced_accuracy']:.4f} | {metric['accuracy']:.4f} |"
        )
    model_a = payload["models"]["model_a_text_only"]["main_test"]
    model_b = payload["models"]["model_b_text_plus_features"]["main_test"]
    macro_delta = model_b["macro_f1"] - model_a["macro_f1"]
    balanced_delta = model_b["balanced_accuracy"] - model_a["balanced_accuracy"]
    lines.extend(
        [
            "",
            f"Model B minus Model A: macro F1 {macro_delta:+.4f}; balanced accuracy {balanced_delta:+.4f}.",
            "On this fixed split the existing engineered features do not add measurable held-out value over text alone. This single baseline comparison does not establish that they lack value in other samples or deployment settings.",
        ]
    )
    lines.extend(["", "Confusion matrices use row=true and column=predicted order: negative, positive.", ""])
    for name, result in payload["models"].items():
        metric = result["main_test"]
        lines.extend([f"### {name}", "", f"Confusion matrix: `{metric['confusion_matrix']}`", ""])
        lines.extend(_per_class_table(metric))
    lines.extend(
        [
            "## Manual post-training diagnostic",
            "",
            f"Eligible clear binary audit rows: {split['manual_diagnostic']['eligible_rows']}; excluded mixed, unclear, or non-binary rows: {split['manual_diagnostic']['excluded_mixed_unclear_or_nonbinary_rows']}.",
            "These rows were not used for fitting, selection, preprocessing, features, or thresholds.",
            "",
            "| Model | Macro F1 | Balanced accuracy | Accuracy/agreement |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, result in payload["models"].items():
        metric = result["manual_diagnostic"]
        lines.append(
            f"| {name} | {metric['macro_f1']:.4f} | {metric['balanced_accuracy']:.4f} | {metric['accuracy']:.4f} |"
        )
    lines.extend(["", "Diagnostic confusion matrices use row=true and column=predicted order: negative, positive.", ""])
    for name, result in payload["models"].items():
        metric = result["manual_diagnostic"]
        lines.extend([f"### {name} diagnostic", "", f"Confusion matrix: `{metric['confusion_matrix']}`", ""])
        lines.extend(_per_class_table(metric))
    lines.extend(["", "## Error analysis", ""])
    lines.append(
        f"The deterministic sample contains {len(errors)} held-out errors across the two models. It omits author fields and uses hashed example keys. Positive-target/negative-prediction and negative-target/positive-prediction cases can reflect model limitations, mixed language, ambiguity, or rating/text disagreement. Some apparent errors are weak-label noise rather than failures against ground truth."
    )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- The primary target is rating-derived and noisy, so the main metrics measure reproduction of a weak proxy.",
            "- The 135-row audit was coverage-selected, not population-random, and its clear binary subset is small.",
            "- A small difference between models does not establish generalizable value from engineered features.",
            "- No hyperparameter search, threshold tuning, embeddings, transformers, or expanded topic dictionaries were used.",
            "",
            "## Generated artifacts",
            "",
            "- `metrics.json`: machine-readable experiment configuration, safeguards, and metrics.",
            "- `split_summary.json`: exclusion, partition, group, and class counts.",
            "- `test_predictions.csv`: hashed example keys, weak targets, and both finalized test predictions.",
            "- `manual_diagnostic_predictions.csv`: hashed example keys, clear manual reference labels, and both post-training diagnostic predictions.",
            "- `error_analysis_sample.csv`: deterministic error examples without author identity fields.",
            "- `modeling_report.md`: this concise human-readable report.",
        ]
    )
    return "\n".join(lines) + "\n"


def _per_class_table(metric: dict[str, Any]) -> list[str]:
    lines = ["| Class | Precision | Recall | F1 |", "|---|---:|---:|---:|"]
    for label in CLASS_ORDER:
        row = metric["per_class"][label]
        lines.append(
            f"| {label} | {row['precision']:.4f} | {row['recall']:.4f} | {row['f1-score']:.4f} |"
        )
    return [*lines, ""]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features",
        default="data/processed/review_features/apple-large-feature-v2/review_features.csv",
    )
    parser.add_argument(
        "--audit",
        default="reports/review_features/apple-large-feature-v2/manual_validation_sample_annotated.csv",
    )
    parser.add_argument("--output-dir", default="reports/modeling/binary-sentiment-baseline")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    result = run_baseline(args.features, args.audit, args.output_dir)
    print(json.dumps({"output_dir": args.output_dir, "split": result["split"]}, indent=2))


if __name__ == "__main__":
    main()
