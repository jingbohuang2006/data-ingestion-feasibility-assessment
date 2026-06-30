# Manual Amazon Response Files

This directory is reserved for browser-captured Amazon review HTML/AJAX responses used for local offline parsing tests.

Do not commit raw browser-captured Amazon responses to GitHub. They may contain CSRF values, temporary pagination tokens, profile URLs, cookies, or session-related values.

The upload-safe evidence derived from those files is stored in:

- `data/processed/amazon_reviews.csv`
- `data/processed/amazon_reviews.jsonl`
- `reports/test_run_summary.json`
- `reports/data_quality_metrics.csv`
- `reports/source_comparison.csv`
- `reports/feasibility_report.md`
