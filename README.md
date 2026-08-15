# Data-Ingestion Feasibility Assessment

## Project Overview

This repository documents an end-to-end review data ingestion and validation workflow developed to support customer-review analytics and downstream sentiment analysis.

The project evolved from an initial feasibility assessment of external review sources into a broader data workflow covering source evaluation, large-scale collection validation, data quality analysis, feature engineering, and manual sentiment-label validation.

### Key Outcomes

- Evaluated Amazon, Steam, Google Play, and Apple App Store review sources across accessibility, reliability, metadata availability, data quality, scalability, and maintainability.
- Selected Apple App Store as the primary validation direction under the tested constraints and collected **6,396 normalized reviews across 20 app/storefront targets**.
- Built reproducible collection, cleaning, normalization, and EDA workflows with explicit handling of missing fields, duplicate records, pagination limitations, low-signal reviews, and collection failures.
- Developed a deterministic feature-engineering layer covering text characteristics, time-based features, metadata availability, repetition indicators, and lexical topic signals while preserving review identifiers and source lineage.
- Completed manual validation on a deterministic **135-review sample** to assess weak sentiment labels and ambiguous cases, including rating-text disagreement, mixed sentiment, neutral reviews, and unclear content.
- Produced versioned configuration, automated tests, validation reports, and reproducible artifacts to support traceability and independent review.

This repository represents validation and analytical infrastructure rather than a production scraping system. Platform access stability, deployment, monitoring, legal/policy review, and production operations remain outside the validated scope.

## Phase 1 Data Sources

### Steam User Reviews

Steam was tested through the public Steam Store review JSON endpoint. The assessment used small request limits, cursor pagination, and polite delays. The preserved evidence shows direct structured access and pagination working for the tested app IDs.

Tested app IDs:

- `730`
- `413150`
- `620`

### Amazon Product Reviews

Amazon live access was treated cautiously. The project does not bypass CAPTCHA, login, robot checks, rate limits, access controls, or session requirements.

Amazon feasibility evidence in the final report is based on **three browser-captured AJAX response files parsed offline**. These files demonstrated that Amazon review HTML/AJAX responses can be parsed, but they do **not** prove repeatable unattended direct access.

The original browser-captured raw Amazon response files may contain CSRF values, profile URLs, session-related values, or temporary pagination tokens. They are intentionally excluded from GitHub upload. The normalized processed output and reports contain only safe derived evidence.

## Project Structure

```text
.
├── README.md
├── AGENTS.md
├── requirements.txt
├── .gitignore
├── .env.example
├── config.example.yaml
├── src/
│   ├── config.py
│   ├── models.py
│   ├── http_utils.py
│   ├── steam_probe.py
│   ├── amazon_probe.py
│   ├── google_play_probe.py
│   ├── apple_app_store_probe.py
│   ├── quality_checks.py
│   ├── comparison.py
│   ├── report_generator.py
│   └── run_assessment.py
├── tests/
│   ├── fixtures/
│   ├── test_amazon_parser.py
│   ├── test_steam_parser.py
│   ├── test_quality_checks.py
│   └── test_comparison.py
├── data/
│   ├── processed/
│   │   ├── amazon_reviews.csv
│   │   ├── amazon_reviews.jsonl
│   │   ├── steam_reviews.csv
│   │   ├── steam_reviews.jsonl
│   │   ├── google_play_reviews.csv
│   │   ├── google_play_reviews.jsonl
│   │   ├── apple_app_store_reviews.csv
│   │   └── apple_app_store_reviews.jsonl
│   └── raw/
│       ├── amazon/
│       └── steam/
└── reports/
    ├── test_run_summary.json
    ├── data_quality_metrics.csv
    ├── source_comparison.csv
    ├── feasibility_report.md
    ├── app_store_test_run_summary.json
    ├── app_store_data_quality_metrics.csv
    ├── app_store_metadata_field_matrix.csv
    ├── app_store_source_comparison.csv
    └── app_store_feasibility_report.md
```

## Setup

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
```

## Configuration

Use `config.example.yaml` as the committed template. Keep local `config.yaml` out of Git.

Steam app IDs:

```yaml
steam:
  app_ids:
    - "730"
    - "413150"
    - "620"
```

Amazon saved response files:

```yaml
amazon:
  saved_response_files:
    - "data/raw/amazon/manual/amazon_response_1.txt"
    - "data/raw/amazon/manual/amazon_response_2.txt"
    - "data/raw/amazon/manual/amazon_response_3.txt"
```

Optional Amazon headers or cookies may be provided through environment variables when explicitly testing a user-provided session:

```text
AMAZON_HEADERS_JSON=
AMAZON_COOKIES_JSON=
```

Do not commit real cookies, headers, authorization values, CSRF tokens, or session data.

Phase 2 app-store defaults:

```yaml
google_play:
  app_name: "YouTube"
  package_id: "com.google.android.youtube"
  country: "us"
  language: "en"

apple_app_store:
  app_name: "YouTube"
  app_id: "544007664"
  country: "us"
  language: "en"
```

Google Play collection uses `google-play-scraper`, an unofficial third-party package. Apple App Store collection uses Apple's public customer-review RSS JSON feed.

## Running The Assessment

Full assessment:

```bash
python -m src.run_assessment --config config.yaml
```

Steam only:

```bash
python -m src.run_assessment --config config.yaml --source steam
```

Amazon only:

```bash
python -m src.run_assessment --config config.yaml --source amazon
```

Offline-only mode:

```bash
python -m src.run_assessment --config config.yaml --offline-only
```

Skip live Amazon requests:

```bash
python -m src.run_assessment --config config.yaml --skip-live-amazon
```

Run only the Phase 2 app-store assessment:

```bash
python -m src.run_assessment --config config.yaml --source app_stores
```

Run one app-store source:

```bash
python -m src.run_assessment --config config.yaml --source google_play
python -m src.run_assessment --config config.yaml --source apple_app_store
```

Run the separate larger Apple App Store validation path:

```bash
python -m src.run_assessment --config config.yaml --source apple_app_store_validation --validation-max-reviews 500 --validation-run-id apple-small-500
```

The validation path writes to isolated run folders and does not overwrite the Phase 2 app-store outputs. Use a small run first, such as 500 or 1,000 reviews, before attempting the configured larger target:

```bash
python -m src.run_assessment --config config.yaml --source apple_app_store_validation --validation-max-reviews 1000 --validation-run-id apple-small-1000
python -m src.run_assessment --config config.yaml --source apple_app_store_validation --validation-run-id apple-target-10000
```

The configured default target is 10,000 Apple App Store reviews across multiple apps/storefronts where feasible. Actual volume may be lower because Apple RSS page depth, app review volume, storefront behavior, network conditions, and conservative caps can limit collection.

## Deterministic Review Features

Generate a separate, run-specific feature dataset from an explicit normalized-review CSV:

```bash
python -m src.review_features \
  --input data/processed/apple_app_store_validation/apple-large-10000/apple_app_store_validation_reviews.csv \
  --config config/review_feature_rules_v1.yaml \
  --output-root data/processed/review_features \
  --run-id apple-large-feature-v2
```

Then generate the deterministic validation report using the observed input count:

```bash
python -m src.review_feature_report \
  --features data/processed/review_features/apple-large-feature-v2/review_features.csv \
  --input-row-count 6396 \
  --output-root reports/review_features \
  --run-id apple-large-feature-v2 \
  --manual-sample-size 135
```

The feature layer remains separate from normalized data. It includes fixed-reference and collection-relative
review ages, separate full-content and body-only repetition indicators, six explicitly named lexical topic
signals, and rating-derived weak sentiment labels. Weak labels are for manual data-quality validation only:
they must not be used as model features or prediction targets. The report run also creates
`manual_validation_sample.csv`; complete its human annotation fields before deciding which sentiment groups
are suitable for baseline usage or which rules require refinement. Follow
`docs/manual_validation_annotation_guidelines.md` for allowed values, decision rules, and completion checks.

The generator preserves one row per normalized review, retains identifiers and lineage, and never overwrites
raw or normalized datasets. Rules are versioned in `config/review_feature_rules_v1.yaml`. See
`docs/review_feature_methodology.md` and `docs/review_feature_data_dictionary.md`.

If a validation run cannot reach the configured target, the generated summary, EDA Markdown, errors table, and pagination table record the actual collected count and observed reason, such as empty RSS pages, request failures, duplicate records, configured page-depth exhaustion, or target/storefront limits.

## Tests

```bash
python -m pytest -q
```

The tests use fixtures and mocked/local parsing only. They do not require live internet access.

## Generated Outputs

Processed normalized review data:

- `data/processed/steam_reviews.csv`
- `data/processed/steam_reviews.jsonl`
- `data/processed/amazon_reviews.csv`
- `data/processed/amazon_reviews.jsonl`

Reports:

- `reports/test_run_summary.json`
- `reports/data_quality_metrics.csv`
- `reports/source_comparison.csv`
- `reports/feasibility_report.md`

Phase 2 app-store outputs:

- `data/processed/google_play_reviews.csv`
- `data/processed/google_play_reviews.jsonl`
- `data/processed/apple_app_store_reviews.csv`
- `data/processed/apple_app_store_reviews.jsonl`
- `reports/app_store_test_run_summary.json`
- `reports/app_store_data_quality_metrics.csv`
- `reports/app_store_metadata_field_matrix.csv`
- `reports/app_store_source_comparison.csv`
- `reports/app_store_feasibility_report.md`

Larger Apple validation outputs are written under run-specific folders:

- `data/processed/apple_app_store_validation/<run_id>/apple_app_store_validation_reviews.csv`
- `data/processed/apple_app_store_validation/<run_id>/apple_app_store_validation_reviews.jsonl`
- `reports/apple_app_store_validation/<run_id>/apple_app_store_validation_summary.json`
- `reports/apple_app_store_validation/<run_id>/apple_app_store_validation_eda.md`
- `reports/apple_app_store_validation/<run_id>/review_volume_by_app.csv`
- `reports/apple_app_store_validation/<run_id>/rating_distribution.csv`
- `reports/apple_app_store_validation/<run_id>/review_text_length.csv`
- `reports/apple_app_store_validation/<run_id>/date_coverage.csv`
- `reports/apple_app_store_validation/<run_id>/missing_fields.csv`
- `reports/apple_app_store_validation/<run_id>/duplicate_records.csv`
- `reports/apple_app_store_validation/<run_id>/language_region_issues.csv`
- `reports/apple_app_store_validation/<run_id>/low_signal_reviews.csv`
- `reports/apple_app_store_validation/<run_id>/pagination_depth_and_failures.csv`
- `reports/apple_app_store_validation/<run_id>/errors.csv`

Raw response files are intentionally not upload-ready because they may contain temporary browser/session artifacts.

## Phase 1 Key Findings

- Steam direct structured access succeeded in the limited test.
- Steam cursor pagination was demonstrated.
- Steam produced 150 unique normalized review records in the preserved processed output.
- Amazon browser-captured AJAX parsing succeeded offline.
- Amazon produced 30 unique normalized review records from three saved response batches.
- Amazon sequential browser-captured pagination was demonstrated in the saved files.
- Amazon unattended direct-request reliability remains unresolved.

## Phase 1 Historical Recommendation

Use Steam for the initial automated technical ingestion prototype because direct structured access and pagination were demonstrated. Preserve the Amazon offline parser as proof that browser-captured Amazon review responses can be normalized, but continue Amazon only through a separate controlled proof of repeatable, approved access before selecting it for production ingestion.

This recommendation is now historical. Stakeholder direction supersedes it: Steam should not be recommended as the main source because its gaming-specific review context is not sufficiently generalizable for broader product intelligence. Amazon remains on hold until repeatable, approved programmatic access is resolved.

## Phase 2 App Store Assessment

The Phase 2 assessment uses YouTube as a shared high-volume app available on both platforms:

- Google Play package ID: `com.google.android.youtube`
- Apple App Store app ID: `544007664`
- Country/storefront: `us`
- Language: `en`

Latest generated Phase 2 evidence in this repository shows:

- Google Play collected 100 unique normalized reviews through `google-play-scraper`.
- Google Play demonstrated two batches in each of two runs, with final dataset duplicate count `0`, cross-run overlap count `100`, cross-run overlap rate `1.0`, and new records in the second run `0`.
- Google Play access is technically feasible in this run, but it depends on an unofficial third-party package and undocumented Google Play behavior.
- Google Play live collection executed through the wrapper, but underlying HTTP request counts are unavailable via `google-play-scraper` and are reported as unavailable rather than zero.
- Apple App Store collected 100 unique normalized reviews through a publicly accessible but undocumented RSS JSON feed.
- Apple App Store demonstrated two pages in each of two runs, with final dataset duplicate count `0`, cross-run overlap count `100`, cross-run overlap rate `1.0`, and new records in the second run `0`.
- The Apple RSS JSON feed is not an official supported Apple review API, and long-term endpoint and schema stability are not guaranteed.
- Two immediate successful runs do not prove long-term repeatability; the observed 100% overlap may only reflect an unchanged recent-review window during two closely timed runs.
- Incremental ingestion is conditionally feasible only while stable review IDs and stable ordering remain available.
- No authentication bypass, CAPTCHA solving, stealth behavior, or access-control circumvention was used.

## Current Recommendation

Apple App Store is the stronger primary app-store source under the current tested constraints because it produced the same 100-review normalized sample as Google Play while using a simpler publicly accessible RSS JSON feed rather than an unofficial third-party wrapper. It is not a risk-free production API. Google Play Store should be retained as a secondary source only after its unofficial access path is approved and monitored. Before production use, both sources need platform-policy review, longer repeatability testing across days, explicit rate limits, monitoring, failure detection, schema-change alerts, and stakeholder/legal approval.

Steam is not recommended as the main Phase 2 source because of stakeholder concerns about commercial relevance and generalizability. Amazon remains on hold because this phase did not resolve repeatable programmatic access.

## Larger Apple App Store Validation

The larger Apple validation path is separate from the Phase 2 app-store assessment. It is intended to answer the next validation question: whether Apple App Store RSS review collection remains useful across multiple apps, categories, and storefronts at a larger sample size.

Configure targets in `config.yaml`:

```yaml
apple_app_store:
  validation_total_reviews: 10000
  validation_reviews_per_target: 1000
  validation_max_pages_per_target: 20
  validation_low_signal_min_text_length: 15
  validation_targets:
    - app_name: "YouTube"
      app_id: "544007664"
      country: "us"
      language: "en"
      category: "video"
    - app_name: "Spotify"
      app_id: "324684580"
      country: "us"
      language: "en"
      category: "music"
```

Start with a small validation run:

```bash
python -m src.run_assessment --config config.yaml --source apple_app_store_validation --validation-max-reviews 500 --validation-run-id apple-small-500
```

Then review the EDA files in `reports/apple_app_store_validation/apple-small-500/`. The EDA covers review volume by app, rating distribution, text length, timestamp/date coverage, missing fields, duplicate records, configured language/storefront notes, low-signal reviews, pagination depth, and failures/errors.

If the validation run stops short of the configured target, review `apple_app_store_validation_eda.md`, `apple_app_store_validation_summary.json`, `errors.csv`, and `pagination_depth_and_failures.csv` for the actual count and observed reason.

The preserved `apple-large-10000` validation run collected 6,396 normalized Apple App Store reviews across 20 configured app/storefront targets. It did not reach the 10,000-review target because the Apple RSS feed exposed limited page depth per app/storefront: several targets returned empty pages before page 10, and several high-volume targets returned unavailable-page responses around page 11. The run also skipped duplicate review IDs rather than inflating the final dataset.

If the small run looks healthy, attempt a larger validation run:

```bash
python -m src.run_assessment --config config.yaml --source apple_app_store_validation --validation-run-id apple-target-10000
```

This remains validation work, not production readiness. The Apple RSS feed is publicly accessible but undocumented, is not an official supported Apple review API, and may change or stop behaving consistently. The validation runner does not include scheduling, storage backfills, monitoring, alerting, legal approval, policy review, or operational failure handling. It does not bypass authentication, CAPTCHA, rate limits, region restrictions, or access controls.

Google Play remains in this repository as a secondary benchmark. The larger validation path does not expand Google Play equally because the current stakeholder direction is to evaluate Apple as the primary candidate while preserving Google Play as comparative evidence.

## Limitations

- The assessment is intentionally small-scale.
- Collected review counts are capped and should not be interpreted as total platform volume.
- Steam is technically convenient but gaming-specific.
- Amazon is commercially broader, but raw browser captures may contain sensitive temporary values and direct unattended access was not proven.
- This project does not provide legal advice; platform terms, access permissions, and institutional requirements must be reviewed before production use.
