# Data-Ingestion Feasibility Assessment

This project evaluates whether **Steam User Reviews** or **Amazon Product Reviews** is the better starting source for a future review-ingestion and sentiment-analysis prototype.

The goal is not to build a production scraper. The project is a small, evidence-based feasibility assessment focused on:

- accessibility
- review volume in a limited sample
- available metadata
- data quality
- commercial value
- long-term maintainability

## Data Sources

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
│   │   └── steam_reviews.jsonl
│   └── raw/
│       ├── amazon/
│       └── steam/
└── reports/
    ├── test_run_summary.json
    ├── data_quality_metrics.csv
    ├── source_comparison.csv
    └── feasibility_report.md
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

Raw response files are intentionally not upload-ready because they may contain temporary browser/session artifacts.

## Key Findings

- Steam direct structured access succeeded in the limited test.
- Steam cursor pagination was demonstrated.
- Steam produced 150 unique normalized review records in the preserved processed output.
- Amazon browser-captured AJAX parsing succeeded offline.
- Amazon produced 30 unique normalized review records from three saved response batches.
- Amazon sequential browser-captured pagination was demonstrated in the saved files.
- Amazon unattended direct-request reliability remains unresolved.

## Recommendation

Use Steam for the initial automated technical ingestion prototype because direct structured access and pagination were demonstrated. Preserve the Amazon offline parser as proof that browser-captured Amazon review responses can be normalized, but continue Amazon only through a separate controlled proof of repeatable, approved access before selecting it for production ingestion.

## Limitations

- The assessment is intentionally small-scale.
- Collected review counts are capped and should not be interpreted as total platform volume.
- Steam is technically convenient but gaming-specific.
- Amazon is commercially broader, but raw browser captures may contain sensitive temporary values and direct unattended access was not proven.
- This project does not provide legal advice; platform terms, access permissions, and institutional requirements must be reviewed before production use.
