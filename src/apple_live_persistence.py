"""Small, bounded Apple collector-to-PostgreSQL persistence workflow."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from .apple_app_store_probe import APPLE_USER_AGENT, _build_apple_url, parse_apple_app_store_reviews
from .database_ingestion import IngestionStore, raw_apple_entries, reconcile_run, utc_now
from .http_utils import PoliteSession


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LiveAppleSettings:
    database_url: str
    app_id: str = "544007664"
    app_name: str = "YouTube"
    country: str = "us"
    language: str = "en"
    category: str | None = "video"
    passes: int = 2
    max_pages_per_pass: int = 1
    max_requests: int = 2
    max_normalized_reviews: int = 25
    request_delay_seconds: float = 1.5
    request_timeout_seconds: float = 20.0
    output_root: Path = ROOT
    run_name: str | None = None

    def validated(self) -> "LiveAppleSettings":
        limits = {
            "passes": (self.passes, 1, 2),
            "max_pages_per_pass": (self.max_pages_per_pass, 1, 2),
            "max_requests": (self.max_requests, 1, 4),
            "max_normalized_reviews": (self.max_normalized_reviews, 1, 100),
        }
        for name, (value, minimum, maximum) in limits.items():
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if self.request_delay_seconds < 1.0:
            raise ValueError("request_delay_seconds must be at least 1.0")
        if not self.app_id.isdigit() or not self.country.islower() or not self.language.islower():
            raise ValueError("app_id must be numeric and country/language must be lowercase")
        return self


def unique_run_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"apple-live-{stamp}-{uuid.uuid4().hex[:8]}"


def request_status(record: Any, response_present: bool, page_number: int,
                   parse_error: str | None, parsed_count: int) -> str:
    """Map one bounded request to a schema-supported outcome category."""
    if not response_present or not record.success:
        if page_number > 1 and record.status_code in {400, 404}:
            return "pagination_limit_or_unavailable_page"
        return "request_failed"
    if parse_error:
        return "json_parse_error"
    if parsed_count == 0:
        return "empty_page"
    return "ok"


def run_live_apple_persistence(settings: LiveAppleSettings, session: Any | None = None) -> dict[str, Any]:
    """Collect a tightly bounded sample and append one unique ingestion run."""
    settings = settings.validated()
    run_name = settings.run_name or unique_run_name()
    if not run_name.startswith("apple-live-"):
        raise ValueError("live run names must start with 'apple-live-'")
    raw_dir = settings.output_root / "data" / "raw" / "apple_live" / run_name
    report_dir = settings.output_root / "reports" / "apple_live" / run_name
    raw_dir.mkdir(parents=True, exist_ok=False)
    report_dir.mkdir(parents=True, exist_ok=False)
    collector = session or PoliteSession(settings.request_timeout_seconds, settings.request_delay_seconds, APPLE_USER_AGENT)
    request_count = normalized_count = 0
    run_id = run_target_id = app_storefront_id = None
    terminal_reason: str | None = None
    fatal_error: Exception | None = None

    try:
        with psycopg.connect(settings.database_url) as conn:
            store = IngestionStore(conn)
            source_id = store.ensure_apple_source()
            safe_config = asdict(settings)
            safe_config.pop("database_url")
            safe_config["output_root"] = "."
            run_id = store.create_run(run_name, "live Apple collector-to-PostgreSQL persistence",
                                      settings.max_normalized_reviews, safe_config, raw_dir, report_dir)
            run_target_id, app_storefront_id = store.resolve_target(
                source_id, run_id, app_id=settings.app_id, app_name=settings.app_name,
                country=settings.country, language=settings.language, category=settings.category,
                target_review_count=settings.max_normalized_reviews,
                max_pages=settings.passes * settings.max_pages_per_pass,
            )
            conn.commit()

            stop = False
            for pass_number in range(1, settings.passes + 1):
                for page_number in range(1, settings.max_pages_per_pass + 1):
                    if request_count >= settings.max_requests:
                        terminal_reason = "request_limit_reached"
                        stop = True
                        break
                    request_count += 1
                    url = _build_apple_url(settings.country, settings.app_id, settings.language, page_number)
                    requested_at = utc_now()
                    http_result = collector.get(url)
                    completed_at = utc_now()
                    content = bytes(http_result.response.content or b"") if http_result.response is not None else b""
                    payload: dict[str, Any] | None = None
                    parse_error: str | None = None
                    if http_result.response is not None and http_result.record.success:
                        try:
                            decoded = json.loads(content.decode("utf-8"))
                            if not isinstance(decoded, dict):
                                raise ValueError("top-level Apple response is not an object")
                            payload = decoded
                        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                            parse_error = str(exc)
                    appearances = raw_apple_entries(payload) if payload is not None else []
                    parsed_appearances = [item for item in appearances if item[3] == "parsed"]
                    distinct_count = len({item[2] for item in parsed_appearances if item[2]})
                    status = request_status(http_result.record, http_result.response is not None, page_number,
                                            parse_error, len(parsed_appearances))
                    request_id = store.add_request(run_target_id, request_count, page_number, url, http_result.record,
                                                   status, len(parsed_appearances), distinct_count,
                                                   requested_at, completed_at)
                    suffix = "json" if payload is not None else "bin"
                    raw_path = raw_dir / f"request_{request_count:03d}_pass_{pass_number}_page_{page_number}.{suffix}"
                    raw_path.write_bytes(content)
                    if http_result.response is not None:
                        payload_id = store.add_payload(request_id, raw_path, content, payload, completed_at)
                        if payload is not None:
                            normalized_by_id = {
                                review.review_id: review.to_dict() for review in parse_apple_app_store_reviews(
                                    payload, settings.app_id, settings.app_name, settings.country,
                                    settings.language, url, page_number
                                ) if review.review_id
                            }
                            for ordinal, entry, review_id, parse_status, entry_error in appearances:
                                raw_id = store.add_raw_record(payload_id, ordinal, entry, review_id, parse_status, entry_error)
                                if parse_status == "parse_error":
                                    store.add_non_normalized_observation(raw_id, "parse_error", completed_at)
                                    continue
                                if parse_status == "non_review_entry":
                                    store.add_non_normalized_observation(raw_id, "non_review_entry", completed_at)
                                    continue
                                identity_id, is_new = store.resolve_identity(app_storefront_id, review_id or "", completed_at)
                                normalized = normalized_by_id.get(review_id)
                                if not is_new:
                                    store.add_non_normalized_observation(raw_id, "repeat_seen", completed_at, identity_id)
                                elif normalized is None:
                                    store.add_non_normalized_observation(raw_id, "parse_error", completed_at)
                                elif normalized_count >= settings.max_normalized_reviews:
                                    store.add_non_normalized_observation(raw_id, "excluded", completed_at, identity_id)
                                    store.add_missing_evidence(run_target_id, "normalization_cap_exceeded", request_id,
                                                               settings.max_normalized_reviews, normalized_count,
                                                               context={"page": page_number, "pass": pass_number,
                                                                        "record_ordinal": ordinal})
                                else:
                                    store.add_normalized(raw_id, identity_id, normalized, completed_at)
                                    normalized_count += 1
                    if status != "ok":
                        store.add_missing_evidence(run_target_id, status, request_id,
                                                   detail=parse_error or http_result.record.error,
                                                   context={"page": page_number, "pass": pass_number})
                        terminal_reason = status
                        stop = True
                    conn.commit()
                    if stop:
                        break
                if stop:
                    break

            target_reached = normalized_count >= settings.max_normalized_reviews
            if terminal_reason == "request_limit_reached":
                store.add_missing_evidence(run_target_id, terminal_reason,
                                           expected=settings.max_requests + 1, observed=settings.max_requests)
            if not terminal_reason and not target_reached:
                terminal_reason = "configured_scope_exhausted"
                store.add_missing_evidence(run_target_id, terminal_reason,
                                           expected=settings.max_normalized_reviews, observed=normalized_count)
            final_status = (
                "completed" if target_reached and terminal_reason is None
                else ("failed" if normalized_count == 0 else "partial")
            )
            store.finalize(run_id, run_target_id, normalized_count, target_reached, final_status, terminal_reason)
            conn.commit()
    except Exception as exc:
        fatal_error = exc
        if run_id is not None:
            with psycopg.connect(settings.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE ingestion_runs SET completed_at=now(),status='failed',stop_reason=%s
                        WHERE run_id=%s AND status='running'""", (f"unhandled_error:{type(exc).__name__}", run_id))
                    if run_target_id is not None:
                        target_status = "partial" if normalized_count else "failed"
                        cur.execute("""UPDATE run_targets SET reviews_collected=%s,status=%s,stop_reason=%s
                            WHERE run_target_id=%s AND status='running'""",
                            (normalized_count, target_status, f"unhandled_error:{type(exc).__name__}", run_target_id))
                conn.commit()

    report: dict[str, Any] = {"run_name": run_name}
    if run_id is not None:
        report.update(reconcile_run(settings.database_url, run_name))
    if fatal_error is not None:
        report["error_type"] = type(fatal_error).__name__
        report["error_message"] = str(fatal_error)
    report_path = report_dir / "live_persistence_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if fatal_error is not None:
        raise fatal_error
    return report


def settings_from_environment() -> LiveAppleSettings:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    return LiveAppleSettings(
        database_url=database_url,
        app_id=os.getenv("APPLE_LIVE_APP_ID", "544007664"),
        app_name=os.getenv("APPLE_LIVE_APP_NAME", "YouTube"),
        country=os.getenv("APPLE_LIVE_COUNTRY", "us").lower(),
        language=os.getenv("APPLE_LIVE_LANGUAGE", "en").lower(),
        category=os.getenv("APPLE_LIVE_CATEGORY", "video") or None,
        passes=int(os.getenv("APPLE_LIVE_PASSES", "2")),
        max_pages_per_pass=int(os.getenv("APPLE_LIVE_MAX_PAGES_PER_PASS", "1")),
        max_requests=int(os.getenv("APPLE_LIVE_MAX_REQUESTS", "2")),
        max_normalized_reviews=int(os.getenv("APPLE_LIVE_MAX_NORMALIZED_REVIEWS", "25")),
        request_delay_seconds=float(os.getenv("APPLE_LIVE_REQUEST_DELAY_SECONDS", "1.5")),
        request_timeout_seconds=float(os.getenv("APPLE_LIVE_REQUEST_TIMEOUT_SECONDS", "20")),
        run_name=os.getenv("APPLE_LIVE_RUN_NAME") or None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", help="Optional second copy of the generated JSON report")
    args = parser.parse_args()
    report = run_live_apple_persistence(settings_from_environment())
    output = json.dumps(report, indent=2, default=str)
    if args.report:
        Path(args.report).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
