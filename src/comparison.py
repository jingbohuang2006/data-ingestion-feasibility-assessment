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

APP_STORE_CRITERIA = [
    "Consistent accessibility",
    "Pagination or batching",
    "Available metadata",
    "Repeated collection",
    "Access limitations",
    "Data quality",
    "Long-term maintainability",
    "Commercial value and generalizability",
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


def build_app_store_comparison(
    results: dict[str, ProbeResult], quality_metrics: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Build a multi-source app-store comparison table."""
    rows = []
    for criterion in APP_STORE_CRITERIA:
        row: dict[str, Any] = {"criterion": criterion}
        for source in ("google_play", "apple_app_store"):
            result = results.get(source, ProbeResult(source=source))
            quality = quality_metrics.get(source, {})
            row[f"{source}_evidence"] = _app_store_evidence(criterion, result, quality)
            row[f"{source}_assessment"] = _app_store_assessment(criterion, result, quality)
        row["confidence"] = _app_store_confidence(results, criterion)
        row["notes"] = _app_store_notes(criterion)
        rows.append(row)
    return pd.DataFrame(rows)


def app_store_recommendation(results: dict[str, ProbeResult]) -> str:
    """Return the Phase 2 recommendation based on observed app-store evidence."""
    google = results.get("google_play", ProbeResult(source="google_play"))
    apple = results.get("apple_app_store", ProbeResult(source="apple_app_store"))
    google_viable = _primary_viability_score(google)
    apple_viable = _primary_viability_score(apple)

    if google_viable > apple_viable:
        return (
            "Google Play Store is the stronger primary app-store source under the current evidence because it exposes "
            "a continuation-token batching path and produced the larger normalized sample in this run. Its main caveat "
            "is that access depends on an unofficial third-party library and undocumented Google Play behavior. Apple "
            "App Store should be retained as a secondary source where its RSS feed remains accessible, but pagination "
            "was not demonstrated for the selected app/storefront. Before production use, both sources need approved "
            "access review, repeat monitoring across days, explicit rate limits, and failure handling. Steam is no "
            "longer recommended as the main source because stakeholder concerns about gaming-specific commercial "
            "relevance supersede the earlier technical recommendation; Amazon remains on hold because repeatable "
            "programmatic access was not resolved in this phase."
        )
    if apple_viable > google_viable:
        return (
            "Apple App Store is the stronger primary app-store source under the current evidence because its public RSS "
            "review feed was more accessible and maintainable in this environment. This is not a risk-free production "
            "API: the feed is publicly accessible but undocumented, is not an official supported Apple review API, and "
            "long-term endpoint and schema stability are not guaranteed. The two immediate successful runs do not prove "
            "long-term repeatability, and the observed 100% cross-run overlap may only reflect an unchanged recent-review "
            "window during closely timed runs. Incremental ingestion is conditionally feasible only while stable review "
            "IDs and stable ordering remain available. Google Play Store should be used as a secondary source only after "
            "the unofficial third-party access path is approved for use and monitored, even though it worked repeatably "
            "in this limited run. Before production use, the selected approach needs monitoring, failure detection, "
            "schema-change alerts, explicit rate limits, stakeholder/legal approval, and approved access review. Steam "
            "is no longer recommended as the main source because stakeholder concerns about gaming-specific commercial "
            "relevance supersede the earlier technical recommendation; Amazon remains on hold because repeatable "
            "programmatic access was not resolved in this phase."
        )
    return (
        "No app store can be selected as a fully verified primary source from the current evidence. Use the stronger "
        "successfully accessible app store as a limited pilot source only if one collected live reviews; otherwise, "
        "treat both Google Play Store and Apple App Store as inconclusive until live access succeeds. Steam is not the "
        "main-source recommendation for Phase 2 due to commercial generalizability concerns, and Amazon remains on hold."
    )


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


def _app_store_evidence(criterion: str, result: ProbeResult, quality: dict[str, Any]) -> str:
    if not result.executed:
        return f"Not executed: {result.skipped_reason}"
    if criterion == "Consistent accessibility":
        return (
            f"method={result.access_method}; method_type={result.access_method_type}; "
            f"request_count={_request_count_text(result)}; success_rate={_request_success_rate_text(result)}; "
            f"request_count_status={result.request_count_status}; live_collection={_live_collection_executed(result)}; "
            f"errors={len(result.errors)}"
        )
    if criterion == "Pagination or batching":
        return (
            f"attempted={result.pages_attempted}; completed={result.pages_completed}; "
            f"pagination_demonstrated={result.pagination_success}; batches={len(result.pagination_batches)}"
        )
    if criterion == "Available metadata":
        return ", ".join(result.available_metadata_fields) or "No normalized metadata observed"
    if criterion == "Repeated collection":
        return (
            f"runs={len(result.run_timestamps)}; repeated_collection={result.repeated_collection_demonstrated}; "
            f"cross_run_overlap_count={_not_applicable(result.overlap_across_repeat_runs)}; "
            f"cross_run_overlap_rate={_not_applicable(result.repeat_run_overlap_rate)}; "
            f"new_records_in_second_run={_not_applicable(result.new_records_in_second_run)}"
        )
    if criterion == "Access limitations":
        return "; ".join(result.access_limitations + result.warnings + result.errors) or "No access limitation observed"
    if criterion == "Data quality":
        return (
            f"rows={quality.get('total_rows')}; unique={quality.get('unique_review_count')}; "
            f"final_dataset_duplicate_count={quality.get('final_dataset_duplicate_count')}; "
            f"cross_run_overlap_count={quality.get('cross_run_overlap_count')}; "
            f"new_records_in_second_run={quality.get('new_records_in_second_run')}; "
            f"empty_text={quality.get('empty_review_text_count')}; "
            f"parser_errors={quality.get('parser_error_count')}"
        )
    if criterion == "Long-term maintainability":
        return f"access_method_type={result.access_method_type}; parser_errors={len(result.parser_errors)}"
    if criterion == "Commercial value and generalizability":
        return "Mobile app reviews are broad product/user feedback and more generalizable than gaming-only Steam reviews."
    return ""


def _app_store_assessment(criterion: str, result: ProbeResult, quality: dict[str, Any]) -> str:
    if not result.executed:
        return "Insufficient evidence."
    if criterion == "Consistent accessibility":
        if result.requests and result.request_success_rate() == 1.0:
            return "Strong in this limited live test."
        if result.source == "google_play" and result.reviews:
            return "Technically feasible in this run, but access depends on an unofficial library."
        return "Inconclusive or failed in this environment."
    if criterion == "Pagination or batching":
        return "Demonstrated." if result.pagination_success else "Not demonstrated."
    if criterion == "Available metadata":
        return "Strong observed metadata coverage." if len(result.available_metadata_fields) >= 8 else "Limited observed metadata coverage."
    if criterion == "Repeated collection":
        return "Demonstrated." if result.repeated_collection_demonstrated else "Not demonstrated."
    if criterion == "Access limitations":
        return "Material limitations observed." if result.access_limitations or result.errors else "No material limitation observed in this small test."
    if criterion == "Data quality":
        if quality.get("total_rows", 0) == 0:
            return "No collected rows to assess."
        if quality.get("duplicates_within_final_dataset", 0) == 0 and quality.get("parser_error_count", 0) == 0:
            return "Acceptable in this limited sample."
        return "Mixed."
    if criterion == "Long-term maintainability":
        if result.access_method_type and "third-party" in result.access_method_type:
            return "Riskier because collection depends on an unofficial wrapper."
        return "Stronger because the access path is a public feed with simple JSON parsing."
    if criterion == "Commercial value and generalizability":
        return "Strong fit for app-product feedback and product intelligence."
    return "Insufficient evidence."


def _app_store_confidence(results: dict[str, ProbeResult], criterion: str) -> str:
    if criterion == "Commercial value and generalizability":
        return "medium qualitative"
    if any(result.executed and result.reviews for result in results.values()):
        return "limited"
    return "low"


def _app_store_notes(criterion: str) -> str:
    if criterion == "Access limitations":
        return "Do not bypass authentication, CAPTCHA, rate limits, region restrictions, or robots/access controls."
    if criterion == "Long-term maintainability":
        return "Official or stable documented access is preferred before production use."
    return ""


def _request_count_text(result: ProbeResult) -> str:
    if result.request_count_status != "available":
        return "unavailable"
    return str(len(result.requests))


def _request_success_rate_text(result: ProbeResult) -> str:
    if result.request_count_status != "available":
        return "unavailable"
    return str(result.request_success_rate())


def _live_collection_executed(result: ProbeResult) -> bool:
    if result.live_request_executed is not None:
        return result.live_request_executed
    return bool(result.requests)


def _primary_viability_score(result: ProbeResult) -> int:
    score = 0
    if result.executed and result.reviews:
        score += 2
    if result.pagination_success:
        score += 1
    if result.repeated_collection_demonstrated:
        score += 1
    if result.incremental_collection_feasible:
        score += 1
    if result.access_method_type and "third-party" in result.access_method_type:
        score -= 1
    if result.errors:
        score -= 1
    return score


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
