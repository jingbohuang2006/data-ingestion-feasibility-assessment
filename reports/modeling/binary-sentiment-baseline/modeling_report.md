# Binary Sentiment Baseline

## Interpretation

This is an exploratory weak-target experiment. The target is derived from ratings (1–2 negative,
4–5 positive), with three-star reviews excluded. It is not manually verified sentiment ground truth.
Rating, the weak label, and all rating-derived fields are excluded from model inputs.

## Reproduce

Run from the repository root:

```bash
python -m src.binary_sentiment_baseline
```

## Data and safeguards

- Feature dataset: `data/processed/review_features/apple-large-feature-v2/review_features.csv` (6,396 rows)
- Audit dataset: `reports/review_features/apple-large-feature-v2/manual_validation_sample_annotated.csv` (135 rows)
- Direct audited rows excluded: 135
- Additional matching normalized-text rows excluded: 19
- Binary modeling population: 5,781 rows
- Train/test: 4,625/1,156 rows using deterministic group-aware splitting
- Identical normalized review text cannot cross partitions; all preprocessing is fitted on training rows only.

## Models and feature controls

- Model A: `review_text` normalized with Unicode NFKC/casefold/whitespace collapse, TF-IDF unigrams and bigrams, and class-balanced logistic regression.
- Model B: the same text representation and classifier on the identical split, plus existing topic signals, row-local text/title quality counts, `low_signal_text`, `language_script_consistent`, app-version availability, publication year/month/day-of-week, App name, and country.
- No hyperparameter search or threshold selection is performed. Every learned preprocessing step is fitted on training rows only.

Explicit model-input denylist:

`annotation_status`, `author_id`, `author_name`, `collected_at`, `developer_response`, `developer_response_date`, `feature_reference_timestamp`, `feature_rule_version`, `full_content_duplication_judgment`, `funny_votes`, `has_developer_reply`, `helpful_votes`, `human_sentiment`, `item_id`, `item_name`, `missing_rating`, `mixed_or_unclear`, `normalized_text_group`, `package_id`, `playtime_at_review`, `playtime_forever`, `rating`, `raw_cursor`, `raw_page_number`, `recommendation`, `repeated_full_content`, `repeated_full_content_fingerprint`, `repeated_full_content_group_size`, `repeated_review_body`, `repeated_review_body_fingerprint`, `repeated_review_body_group_size`, `review_age_at_collection_days`, `review_body_duplication_judgment`, `review_id`, `sentiment_agreement`, `source_url`, `split_assignment`, `topic_signal_relevance`, `verified_purchase`, `weak_sentiment_label`

## Main held-out evaluation

| Model | Macro F1 | Balanced accuracy | Accuracy |
|---|---:|---:|---:|
| model_a_text_only | 0.8220 | 0.8196 | 0.8296 |
| model_b_text_plus_features | 0.8143 | 0.8127 | 0.8218 |

Model B minus Model A: macro F1 -0.0077; balanced accuracy -0.0069.
On this fixed split the existing engineered features do not add measurable held-out value over text alone. This single baseline comparison does not establish that they lack value in other samples or deployment settings.

Confusion matrices use row=true and column=predicted order: negative, positive.

### model_a_text_only

Confusion matrix: `[[599, 87], [110, 360]]`

| Class | Precision | Recall | F1 |
|---|---:|---:|---:|
| negative | 0.8449 | 0.8732 | 0.8588 |
| positive | 0.8054 | 0.7660 | 0.7852 |

### model_b_text_plus_features

Confusion matrix: `[[591, 95], [111, 359]]`

| Class | Precision | Recall | F1 |
|---|---:|---:|---:|
| negative | 0.8419 | 0.8615 | 0.8516 |
| positive | 0.7907 | 0.7638 | 0.7771 |

## Manual post-training diagnostic

Eligible clear binary audit rows: 88; excluded mixed, unclear, or non-binary rows: 47.
These rows were not used for fitting, selection, preprocessing, features, or thresholds.

| Model | Macro F1 | Balanced accuracy | Accuracy/agreement |
|---|---:|---:|---:|
| model_a_text_only | 0.9273 | 0.9330 | 0.9318 |
| model_b_text_plus_features | 0.8947 | 0.9196 | 0.8977 |

Diagnostic confusion matrices use row=true and column=predicted order: negative, positive.

### model_a_text_only diagnostic

Confusion matrix: `[[52, 4], [2, 30]]`

| Class | Precision | Recall | F1 |
|---|---:|---:|---:|
| negative | 0.9630 | 0.9286 | 0.9455 |
| positive | 0.8824 | 0.9375 | 0.9091 |

### model_b_text_plus_features diagnostic

Confusion matrix: `[[47, 9], [0, 32]]`

| Class | Precision | Recall | F1 |
|---|---:|---:|---:|
| negative | 1.0000 | 0.8393 | 0.9126 |
| positive | 0.7805 | 1.0000 | 0.8767 |


## Error analysis

The deterministic sample contains 18 held-out errors across the two models. It omits author fields and uses hashed example keys. Positive-target/negative-prediction and negative-target/positive-prediction cases can reflect model limitations, mixed language, ambiguity, or rating/text disagreement. Some apparent errors are weak-label noise rather than failures against ground truth.

## Limitations

- The primary target is rating-derived and noisy, so the main metrics measure reproduction of a weak proxy.
- The 135-row audit was coverage-selected, not population-random, and its clear binary subset is small.
- A small difference between models does not establish generalizable value from engineered features.
- No hyperparameter search, threshold tuning, embeddings, transformers, or expanded topic dictionaries were used.

## Generated artifacts

- `metrics.json`: machine-readable experiment configuration, safeguards, and metrics.
- `split_summary.json`: exclusion, partition, group, and class counts.
- `test_predictions.csv`: hashed example keys, weak targets, and both finalized test predictions.
- `manual_diagnostic_predictions.csv`: hashed example keys, clear manual reference labels, and both post-training diagnostic predictions.
- `error_analysis_sample.csv`: deterministic error examples without author identity fields.
- `modeling_report.md`: this concise human-readable report.
