"""Evidence-based source comparison and recommendation logic."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .models import ProbeResult


CRITERIA = [
    "Accessibility",
    "Review volume",
    "Available metadata",
    "Data quality",
    "Commercial value",
    "Long-term maintainability",
]


def build_comparison(amazon: ProbeResult, steam: ProbeResult, quality_metrics: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Build the requested comparison table."""
    rows = []
    amazon_quality = quality_metrics.get("amazon", {})
    steam_quality = quality_metrics.get("steam", {})
    for criterion in CRITERIA:
        rows.append(
            {
                "criterion": criterion,
                "amazon_evidence": _evidence(criterion, amazon, amazon_quality),
                "steam_evidence": _evidence(criterion, steam, steam_quality),
                "amazon_assessment": _assessment(criterion, amazon, amazon_quality, "amazon"),
                "steam_assessment": _assessment(criterion, steam, steam_quality, "steam"),
                "confidence": _confidence(amazon, steam, criterion),
                "notes": _notes(criterion),
            }
        )
    return pd.DataFrame(rows)


def preliminary_recommendation(amazon: ProbeResult, steam: ProbeResult) -> str:
    """Return a conditional recommendation based only on observed evidence."""
    steam_reliable = steam.executed and bool(steam.reviews) and not steam.blocked and steam.request_success_rate() == 1.0
    amazon_offline_parseable = amazon.executed and bool(amazon.reviews) and bool(amazon.offline_parsing_executed)
    amazon_reliable = amazon.executed and bool(amazon.reviews) and not amazon.blocked and amazon.request_success_rate() in (None, 1.0)
    amazon_live_ran = bool(amazon.requests)

    if steam_reliable and amazon_offline_parseable and not amazon_live_ran:
        return (
            "Use Steam for the initial automated technical prototype because direct structured access and pagination "
            "were successfully demonstrated. Amazon browser-response parsing is also technically feasible and "
            "commercially broader, but unattended direct access remains unresolved. Continue Amazon only through a "
            "controlled browser-based or otherwise approved access proof of concept before selecting it for automated "
            "production ingestion."
        )

    if steam_reliable and (amazon.blocked or not amazon_live_ran):
        return (
            "Preliminary recommendation: use Steam for the initial technical prototype, while treating Amazon as "
            "commercially important but requiring additional access feasibility work."
        )
    if amazon_reliable and amazon_live_ran and amazon.pagination_success:
        return (
            "Preliminary recommendation: Amazon may be suitable for the next prototype based on this limited test, "
            "but broader repeated testing is still required."
        )
    if steam_reliable and not amazon_reliable:
        return (
            "Preliminary recommendation: use a phased approach: validate ingestion with Steam first, then continue "
            "Amazon feasibility testing before committing to it as the main source."
        )
    return "No final source winner is supported by the current evidence; additional configured live or saved-response tests are required."


def _evidence(criterion: str, result: ProbeResult, quality: dict[str, Any]) -> str:
    if not result.executed:
        return f"Not executed: {result.skipped_reason}"
    if criterion == "Accessibility":
        if result.source == "amazon" and result.offline_parsing_executed and not result.requests:
            return (
                f"Direct live accessibility was not tested in this run. Offline parsing succeeded for "
                f"{result.saved_response_batch_count} browser-captured response batches containing "
                f"{len(result.reviews)} unique reviews, and sequential pagination was demonstrated."
            )
        return (
            f"{len(result.requests)} requests, success rate {result.request_success_rate()}, "
            f"blocked={result.blocked}, pagination={result.pagination_success}"
        )
    if criterion == "Review volume":
        return f"{len(result.reviews)} normalized reviews collected; raw reviews returned={result.raw_reviews_returned}"
    if criterion == "Available metadata":
        return ", ".join(result.available_metadata_fields) or "No normalized metadata observed"
    if criterion == "Data quality":
        repeat_overlap = quality.get("overlap_across_repeat_runs")
        return (
            f"duplicates_within_final_dataset={quality.get('duplicates_within_final_dataset')}, "
            f"repeat_overlap={_not_applicable(repeat_overlap)}, "
            f"empty_text={quality.get('empty_review_text_count')}, parser_errors={quality.get('parser_error_count')}"
        )
    if criterion == "Commercial value":
        return "Qualitative criterion; not measured by HTTP probe."
    if criterion == "Long-term maintainability":
        blocked = result.blocking_status or _not_applicable(result.blocked)
        return f"parser_errors={len(result.parser_errors)}, warnings={len(result.warnings)}, blocked={blocked}"
    return ""


def _assessment(criterion: str, result: ProbeResult, quality: dict[str, Any], source: str) -> str:
    if criterion == "Commercial value":
        return (
            "Broad product-review relevance for customer/product insight."
            if source == "amazon"
            else "Rich user feedback, but gaming-specific commercial scope."
        )
    if not result.executed:
        return "Insufficient evidence"
    if criterion == "Accessibility":
        if source == "amazon" and result.offline_parsing_executed and not result.requests:
            return "Offline parseability and browser-captured pagination demonstrated; direct automated accessibility unresolved."
        if result.blocked:
            return "Weak: blocking or access friction observed."
        if result.request_success_rate() == 1.0:
            return "Strong in this limited test."
        if source == "amazon" and result.requests:
            return "Configured live request did not return usable review content; Amazon feasibility remains unresolved."
        return "Insufficient or mixed evidence."
    if criterion == "Long-term maintainability":
        if source == "steam":
            return "Stronger: structured public JSON response."
        return "Riskier: may depend on HTML, sessions, or anti-bot controls."
    if criterion == "Review volume":
        return "Limited test only; collected count is not total platform volume."
    if criterion == "Available metadata":
        count = len(result.available_metadata_fields)
        return "Strong observed metadata coverage." if count >= 8 else "Limited observed metadata coverage."
    if criterion == "Data quality":
        if quality.get("total_rows", 0) == 0:
            return "Not enough evidence."
        if quality.get("duplicates_within_final_dataset", 0) == 0 and quality.get("overlap_across_repeat_runs", 0):
            return "Final dataset is deduplicated; repeat-run overlap is consistency evidence."
        if quality.get("parser_error_count", 0):
            return "Mixed: parser errors observed."
        return "Acceptable in this limited sample."
    return "Insufficient evidence"


def _confidence(amazon: ProbeResult, steam: ProbeResult, criterion: str) -> str:
    if criterion == "Commercial value":
        return "medium qualitative"
    if amazon.executed or steam.executed:
        return "limited"
    return "low"


def _notes(criterion: str) -> str:
    if criterion == "Review volume":
        return "The configured cap prevents measuring total platform inventory."
    if criterion == "Commercial value":
        return "Commercial relevance should be evaluated separately from technical ease."
    if criterion == "Long-term maintainability":
        return "Structured endpoints are usually less fragile than page HTML parsing."
    return ""


def _not_applicable(value: Any) -> str:
    return "not applicable" if value is None else str(value)
