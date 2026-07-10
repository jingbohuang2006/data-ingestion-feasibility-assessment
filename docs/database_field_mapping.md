# Database Field Mapping

This document maps existing repository artifacts to the proposed PostgreSQL schema. It is a design artifact only; no historical outputs are loaded during this stage.

## Current Artifacts

Primary Apple validation artifacts:

- `data/processed/apple_app_store_validation/<run_id>/apple_app_store_validation_reviews.csv`
- `data/processed/apple_app_store_validation/<run_id>/apple_app_store_validation_reviews.jsonl`
- `data/raw/apple_app_store_validation/<run_id>/*.json`
- `reports/apple_app_store_validation/<run_id>/apple_app_store_validation_summary.json`
- `reports/apple_app_store_validation/<run_id>/pagination_depth_and_failures.csv`
- `reports/apple_app_store_validation/<run_id>/errors.csv`
- `reports/apple_app_store_validation/<run_id>/missing_fields.csv`
- `reports/apple_app_store_validation/<run_id>/duplicate_records.csv`
- `reports/apple_app_store_validation/<run_id>/low_signal_reviews.csv`
- `reports/apple_app_store_validation/<run_id>/date_coverage.csv`
- `reports/apple_app_store_validation/<run_id>/rating_distribution.csv`
- `reports/apple_app_store_validation/<run_id>/review_text_length.csv`
- `reports/apple_app_store_validation/<run_id>/language_region_issues.csv`
- `reports/apple_app_store_validation/<run_id>/review_volume_by_app.csv`

Phase 2 benchmark artifacts:

- `data/processed/apple_app_store_reviews.csv`
- `data/processed/apple_app_store_reviews.jsonl`
- `data/processed/google_play_reviews.csv`
- `data/processed/google_play_reviews.jsonl`
- `reports/app_store_test_run_summary.json`
- `reports/app_store_data_quality_metrics.csv`
- `reports/app_store_metadata_field_matrix.csv`
- `reports/app_store_source_comparison.csv`

## Summary JSON Mapping

`apple_app_store_validation_summary.json`

| Existing field | Proposed table.column |
| --- | --- |
| `run_id` | `ingestion_runs.external_run_name` |
| `phase` | `ingestion_runs.phase` |
| `execution_timestamp` | `ingestion_runs.completed_at` |
| `target_review_count` | `ingestion_runs.target_review_count` |
| `reviews_collected` | `ingestion_runs.reviews_collected` |
| `target_reached` | `ingestion_runs.target_reached` |
| `shortfall_reason` | `ingestion_runs.stop_reason` |
| full summary object | `ingestion_runs.config` or future `run_summary_json` if added |
| `processed_output_dir` | `ingestion_runs.processed_output_path` |
| `reports_output_dir` | `ingestion_runs.reports_output_path` |
| `raw_output_dir` | `ingestion_runs.raw_output_path` |
| `limitations` | `review_sources.limitations` and/or `quality_flags.flag_value` |
| `targets[].app_name` | `apps.canonical_name` |
| `targets[].category` | `apps.category` and `app_storefronts.configured_category` |
| `targets[].app_id` | `source_apps.source_app_identifier` |
| `targets[].country` | `storefronts.country_code` |
| `targets[].language` | `storefronts.language_code` |

## Validation Reviews CSV/JSONL Mapping

`apple_app_store_validation_reviews.csv` and `.jsonl`

| Existing normalized field | Proposed table.column |
| --- | --- |
| `source` | `normalized_reviews.source_code`; also joins `review_sources.source_code` |
| `app_name` | `apps.canonical_name` |
| `item_id` | `source_apps.source_app_identifier` |
| `package_id` | `source_apps.source_app_identifier` for Google Play only |
| `item_name` | `source_apps.metadata->>'item_name'` |
| `review_id` | `normalized_reviews.source_review_id`; `review_identities.source_review_id` |
| `review_title` | `normalized_reviews.review_title` |
| `review_text` | `normalized_reviews.review_text` |
| `rating` | `normalized_reviews.rating` |
| `recommendation` | `normalized_reviews.normalized_json->'recommendation'` for non-app-store sources |
| `review_date` | `normalized_reviews.review_date` |
| `author_id` | `normalized_reviews.author_id` |
| `author_name` | `normalized_reviews.author_name` |
| `verified_purchase` | `normalized_reviews.normalized_json->'verified_purchase'` |
| `helpful_votes` | `normalized_reviews.helpful_votes` |
| `funny_votes` | `normalized_reviews.normalized_json->'funny_votes'` |
| `playtime_forever` | `normalized_reviews.normalized_json->'playtime_forever'` |
| `playtime_at_review` | `normalized_reviews.normalized_json->'playtime_at_review'` |
| `app_version` | `normalized_reviews.app_version` |
| `language` | `storefronts.language_code` |
| `country` | `storefronts.country_code` |
| `developer_response` | `normalized_reviews.developer_response` |
| `developer_response_date` | `normalized_reviews.developer_response_date` |
| `source_url` | `normalized_reviews.source_url`; `collection_requests.request_url` |
| `collected_at` | `normalized_reviews.collected_at` |
| `raw_page_number` | `normalized_reviews.raw_page_number`; `collection_requests.page_number` |
| `raw_cursor` | `normalized_reviews.raw_cursor`; `collection_requests.cursor_out` |
| full row | `normalized_reviews.normalized_json` |
| canonical row hash | `normalized_reviews.normalized_hash` |

Backfill should create one `raw_review_records` row for each raw review entry where raw payloads are available. The normalized row should reference that raw row through `normalized_reviews.raw_record_id`.

## Raw Payload Mapping

`data/raw/apple_app_store_validation/<run_id>/apple_app_store_<app_id>_page<page>_<timestamp>.json`

| Existing fact | Proposed table.column |
| --- | --- |
| raw file path | `raw_payloads.storage_path` |
| raw JSON content | `raw_payloads.payload_json` |
| SHA-256 hash of raw bytes or canonical JSON | `raw_payloads.payload_sha256` |
| app ID in filename | `source_apps.source_app_identifier` |
| page number in filename | `collection_requests.page_number` |
| timestamp in filename | `raw_payloads.captured_at` when no better request timestamp exists |

The filesystem path provides parity with current artifacts and allows exact raw-file inspection. `payload_json` supports direct database inspection. `payload_sha256` links the two and should be recomputed during backfill or validation to detect drift.

## Pagination And Request Evidence Mapping

`pagination_depth_and_failures.csv`

| Existing field | Proposed table.column |
| --- | --- |
| `app_name` | `apps.canonical_name` |
| `app_id` | `source_apps.source_app_identifier` |
| `category` | `app_storefronts.configured_category` |
| `country` | `storefronts.country_code` |
| `language` | `storefronts.language_code` |
| `page` | `collection_requests.page_number` |
| `raw_review_count` | `collection_requests.raw_review_count` |
| `distinct_review_count` | `collection_requests.distinct_review_count` |
| `distinct_from_previous_page` | `collection_requests.distinct_from_previous_page` |
| `status` | `collection_requests.status_category` or `run_targets.status` |
| `target_limit` | `run_targets.target_review_count` |
| `reviews_collected_for_target` | `run_targets.reviews_collected` |
| `max_pages_per_target` | `run_targets.max_pages` |
| `duplicate_review_id_count` | `quality_flags.flag_value->>'duplicate_review_id_count'` |
| `duplicate_review_ids_sample` | `quality_flags.flag_value->'duplicate_review_ids_sample'` |

Rows with `status = target_limit_not_reached` are target-level stop evidence and should populate `missing_or_excluded_records` as well as `run_targets.stop_reason`.

## Request Records Mapping

`RequestRecord` objects currently produced by the live Apple probes map to `collection_requests`.

| Current field | Proposed table.column |
| --- | --- |
| `url` | `collection_requests.request_url` |
| `status_code` | `collection_requests.http_status_code` |
| `elapsed_seconds` | `collection_requests.elapsed_seconds` |
| `success` | `collection_requests.success` |
| `content_type` | `collection_requests.content_type` |
| `response_size` | `collection_requests.response_size_bytes` |
| `error` | `collection_requests.error_message` |
| `blocked` | `collection_requests.blocked` |

For Google Play, the current wrapper does not expose equivalent HTTP status, headers, or response-size evidence. Future persistence should still create `collection_requests` rows for wrapper batches with `status_category = 'wrapper_evidence_incomplete'` when only wrapper-level evidence is available.

## EDA Output Mapping

| Existing EDA file | Proposed database representation |
| --- | --- |
| `missing_fields.csv` | `quality_flags` with `flag_type = 'missing_field'`, plus aggregate reports from `normalized_reviews`. |
| `duplicate_records.csv` | `review_identities` and `review_observations`, plus `quality_flags` for duplicate summaries. |
| `low_signal_reviews.csv` | `quality_flags` linked to `normalized_reviews` with `flag_type = 'low_signal_review'`. |
| `errors.csv` | `quality_flags` linked to `collection_requests` or `ingestion_runs` context; severe request errors remain in `collection_requests`. |
| `date_coverage.csv` | Derived aggregate from `normalized_reviews.review_date`; optional quality flags for missing dates. |
| `rating_distribution.csv` | Derived aggregate from `normalized_reviews.rating`. |
| `review_text_length.csv` | Derived aggregate from `normalized_reviews.review_text`; low-signal row flags in `quality_flags`. |
| `language_region_issues.csv` | `quality_flags` or source limitation notes because independent language detection is not currently performed. |
| `review_volume_by_app.csv` | Derived aggregate over `normalized_reviews`, `apps`, and `storefronts`. |

## Backfill Notes

Historical backfill should be idempotent. Use existing run folder names as `ingestion_runs.external_run_name`, raw file hashes for `raw_payloads.payload_sha256`, and conservative review identities for duplicate detection. Backfill must not change the existing file artifacts.
