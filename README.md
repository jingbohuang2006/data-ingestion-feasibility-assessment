# Data-Ingestion Feasibility Assessment

This project evaluates review sources for a future review-ingestion and sentiment-analysis prototype.

- **Phase 1** preserved the historical Amazon Product Reviews vs. Steam User Reviews assessment.
- **Phase 2** assesses Google Play Store and Apple App Store reviews as candidate primary sources for broader product-intelligence work.

The goal is not to build a production scraper. The project is a small, evidence-based feasibility assessment focused on:

- accessibility
- review volume in a limited sample
- available metadata
- data quality
- commercial value
- long-term maintainability

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

## PostgreSQL Ingestion Workflows

The repository includes database/schema artifacts and two explicitly invoked PostgreSQL workflows. Neither runs as part of the general assessment command:

1. **Controlled historical backfill** loads preserved validation datasets and their existing raw/report artifacts.
2. **Live collector persistence** collects a newly observed, tightly bounded Apple sample directly into PostgreSQL while also preserving unique run-specific raw files and a reconciliation report.

The proposed target database is PostgreSQL, with SQLAlchemy and Alembic as the intended implementation path. The design preserves Apple App Store as the primary source and Google Play as a secondary benchmark. It records successful review data and unsuccessful collection evidence, including failed requests, empty pages, pagination limits, target shortfalls, missing/excluded records, quality flags, raw payload hashes, and raw-to-normalized traceability.

Schema artifacts:

- `docs/database_schema_design.md`
- `docs/database_field_mapping.md`
- `docs/database_example_queries.sql`
- `db/schema.sql`
- `alembic/versions/0001_initial_review_ingestion_schema.py`

Historical validation outputs are not loaded automatically. Live collection is also never started by migrations, tests, or the historical loader. Both workflows require an explicit command and database URL.

### Database migration and tests

Set a PostgreSQL connection URL using the standard environment variable:

```bash
export DATABASE_URL='<postgresql-connection-url>'
alembic upgrade head
alembic current
alembic downgrade base
alembic upgrade head
```

Run the normal and live-database tests with:

```bash
python -m pytest -q -m "not postgresql"
TEST_DATABASE_URL="$DATABASE_URL" python -m pytest -q -m postgresql
```

The PostgreSQL tests are skipped when `TEST_DATABASE_URL` is absent. They run real upgrades, schema inspection, downgrade/re-upgrade, representative writes, a mocked-network live persistence path, constraint checks, and every example/reconciliation query when it is present. They must point only to a disposable database.

### Controlled historical backfill

Load the preserved Apple validation evidence in controlled order:

```bash
python -m src.database_load apple-small-500 --report reports/database_load_test/apple-small-500.json
python -m src.database_load apple-large-10000 --report reports/database_load_test/apple-large-10000.json
```

The loader is deterministic: raw files are ordered by capture timestamp, feed entries retain their original ordinal, identity is scoped by source/app/storefront/review ID, the first contextual appearance receives the normalized row, and later appearances remain as `duplicate_skipped` observations.

This controlled loader is only for the preserved `apple-small-500` and `apple-large-10000` validation datasets. It intentionally retains their established replacement semantics for an identically named historical run. Do not use it for newly collected data.

### Controlled live Apple persistence

The live workflow is append-only and uses a unique `apple-live-<timestamp>-<suffix>` run name unless `APPLE_LIVE_RUN_NAME` is explicitly provided. An existing run or output directory is never deleted or replaced. Its conservative default scope is one app/storefront, two passes, one page per pass, two total HTTP requests, and at most 25 newly normalized reviews:

```bash
export DATABASE_URL='<postgresql-connection-url>'
export APPLE_LIVE_APP_ID=544007664
export APPLE_LIVE_APP_NAME=YouTube
export APPLE_LIVE_COUNTRY=us
export APPLE_LIVE_LANGUAGE=en
export APPLE_LIVE_PASSES=2
export APPLE_LIVE_MAX_PAGES_PER_PASS=1
export APPLE_LIVE_MAX_REQUESTS=2
export APPLE_LIVE_MAX_NORMALIZED_REVIEWS=25
python -m src.apple_live_persistence
```

The implementation enforces hard safety ceilings of 2 passes, 2 pages per pass, 4 requests, and 100 normalized reviews. A delay of at least one second is required. All returned feed entries are stored as raw appearances before normalization decisions, including repeated reviews, app metadata, malformed entries, and entries beyond the normalization cap. Repeats and excluded appearances remain explicit observations rather than being silently dropped.

Each run writes raw responses to `data/raw/apple_live/<run_name>/` and its JSON report to `reports/apple_live/<run_name>/live_persistence_report.json`. The report includes app/storefront/target/request counts, raw appearances, normalized reviews, repeat observations, request outcomes, scope/exclusion categories, quality flags, reconciliation issues, and final run status.

Request/page evidence distinguishes:

- `ok` and `empty_page` successful responses;
- `request_failed` transport or HTTP failures;
- `json_parse_error` malformed response bodies;
- `pagination_limit_or_unavailable_page` later-page 400/404 limits;
- `normalization_cap_exceeded` and `configured_scope_exhausted` intentional scope/exclusion evidence, not request or page failures.

The reconciliation output keeps those groups separate. `collection_issue_pages` aggregates failed, empty, malformed, and pagination-limited pages. `scope_limited_pages` counts successful pages associated with an intentional cap or configured scope limit; it is not included in `collection_issue_pages`.

Do not commit real database URLs, credentials, or locally generated live raw payloads without review. The live command above should only be run after migrations and mocked/PostgreSQL tests pass and after explicit approval for the network collection.

### Controlled Live Persistence Test

The approved controlled test ran Apple ID `544007664` (YouTube) against one `us/en` storefront. It used two collection passes with one page per pass, producing two successful HTTP requests. Both raw payloads remain local and ignored; the safe reconciliation report is preserved at `reports/apple_live/apple-live-20260717T120724Z-3e66c24f/live_persistence_report.json`.

Results:

- 1 app, 1 storefront, and 1 run target;
- 2 successful HTTP requests;
- 100 raw review appearances;
- 25 normalized reviews;
- 50 repeated observations;
- 25 excluded observations caused by the approved normalization cap;
- 0 failed, empty, malformed, or limited pages;
- 0 reconciliation issues and 0 integrity issues;
- final run status: `completed`;
- validation suite: 63 passed, 0 failed, 0 skipped.

The report's `scope_limited_pages = 1` is deliberate cap evidence, while `collection_issue_pages = 0`. The first successful page returned 50 review appearances: 25 were normalized and the remaining 25 were preserved as explicit `excluded` observations after the approved 25-review normalization cap was reached. It does not indicate an HTTP failure, empty response, malformed response, pagination limit, or interrupted collection.

## Limitations

- The assessment is intentionally small-scale.
- Collected review counts are capped and should not be interpreted as total platform volume.
- Steam is technically convenient but gaming-specific.
- Amazon is commercially broader, but raw browser captures may contain sensitive temporary values and direct unattended access was not proven.
- This project does not provide legal advice; platform terms, access permissions, and institutional requirements must be reviewed before production use.
