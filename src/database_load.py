"""Deterministic PostgreSQL backfill for preserved Apple validation runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from .database_ingestion import IngestionStore, canonical_hash, raw_apple_entries, reconcile_run


ROOT = Path(__file__).resolve().parents[1]
RAW_NAME = re.compile(r"apple_app_store_(?P<app_id>\d+)_page(?P<page>\d+)_(?P<stamp>.+)\.json$")


def _value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def _timestamp_from_name(path: Path) -> datetime:
    match = RAW_NAME.match(path.name)
    if not match:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    stamp = match.group("stamp").replace("Z0000", "+00:00")
    return datetime.fromisoformat(stamp)


def _raw_entries(payload: dict[str, Any]) -> list[tuple[int, dict[str, Any], str | None, str]]:
    return [(ordinal, entry, review_id, status) for ordinal, entry, review_id, status, _ in raw_apple_entries(payload)]


def load_apple_validation_run(database_url: str, run_name: str, root: Path = ROOT) -> dict[str, Any]:
    reports = root / "reports" / "apple_app_store_validation" / run_name
    processed = root / "data" / "processed" / "apple_app_store_validation" / run_name
    raw_dir = root / "data" / "raw" / "apple_app_store_validation" / run_name
    summary = json.loads((reports / "apple_app_store_validation_summary.json").read_text(encoding="utf-8"))
    reviews = pd.read_csv(processed / "apple_app_store_validation_reviews.csv", dtype={"review_id": str, "item_id": str})
    pagination = pd.read_csv(reports / "pagination_depth_and_failures.csv", dtype={"app_id": str})
    raw_files = sorted(raw_dir.glob("*.json"), key=_timestamp_from_name)
    effective_target = int(run_name.rsplit("-", 1)[-1])
    target_reached = len(reviews) >= effective_target

    files_by_key: dict[tuple[str, int], list[Path]] = defaultdict(list)
    for path in raw_files:
        match = RAW_NAME.match(path.name)
        if match:
            files_by_key[(match.group("app_id"), int(match.group("page")))].append(path)

    execution_time = datetime.fromisoformat(summary["execution_timestamp"])
    normalized_lookup: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    for row in reviews.to_dict("records"):
        key = (str(row["item_id"]), str(row["country"]), str(row["language"]), str(row["review_id"]), int(row["raw_page_number"]))
        normalized_lookup[key] = {k: _value(v) for k, v in row.items()}

    with psycopg.connect(database_url) as conn:
        store = IngestionStore(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingestion_runs WHERE external_run_name = %s", (run_name,))
            source_id = store.ensure_apple_source()
            cur.execute("""
                INSERT INTO ingestion_runs(external_run_name, phase, started_at, completed_at, status,
                    target_review_count, reviews_collected, target_reached, stop_reason, config,
                    processed_output_path, reports_output_path, raw_output_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING run_id
            """, (run_name, summary["phase"], execution_time, execution_time,
                  "completed" if target_reached else "partial", effective_target,
                  len(reviews), target_reached, summary.get("shortfall_reason"),
                  Jsonb({"source_summary": summary}),
                  str(processed), str(reports), str(raw_dir)))
            run_id = cur.fetchone()[0]

            contexts: dict[tuple[str, str, str], dict[str, Any]] = {}
            for target in summary["targets"]:
                app_id, country, language = str(target["app_id"]), target["country"], target["language"]
                app_storefront_id = store.resolve_app_storefront(
                    source_id, app_id=app_id, app_name=target["app_name"], country=country,
                    language=language, category=target.get("category"),
                )
                target_rows = reviews[(reviews.item_id.astype(str) == app_id) & (reviews.country == country) & (reviews.language == language)]
                collected = len(target_rows)
                target_evidence = pagination[
                    (pagination["app_id"].astype(str).str.replace(r"\.0$", "", regex=True) == app_id)
                    & (pagination["country"] == country)
                    & (pagination["language"] == language)
                    & (pagination["status"] == "target_limit_not_reached")
                ]
                if not target_evidence.empty and "target_limit" in target_evidence:
                    target_limit = int(target_evidence.iloc[0]["target_limit"])
                elif collected:
                    target_limit = max(250, collected)
                else:
                    target_limit = None
                target_status = "skipped" if not collected else ("completed" if target_limit and collected >= target_limit else "partial")
                cur.execute("""
                    INSERT INTO run_targets(run_id, app_storefront_id, target_review_count, max_pages,
                        reviews_collected, status, stop_reason)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING run_target_id
                """, (run_id, app_storefront_id, target_limit, int(target_rows.raw_page_number.max()) if collected else None,
                      collected, target_status,
                      None if target_status in {"completed", "skipped"} else "target_limit_not_reached"))
                contexts[(app_id, country, language)] = {
                    "run_target_id": cur.fetchone()[0], "app_storefront_id": app_storefront_id,
                    "target_limit": target_limit, "collected": collected,
                }

            request_by_file: dict[Path, Any] = {}
            request_sequence: dict[Any, int] = defaultdict(int)
            file_offsets: dict[tuple[str, int], int] = defaultdict(int)
            page_rows = pagination[pagination["page"].notna()].to_dict("records")
            for index, row in enumerate(page_rows):
                app_id = str(row["app_id"]).removesuffix(".0")
                country, language, page = str(row["country"]), str(row["language"]), int(row["page"])
                context = contexts[(app_id, country, language)]
                request_sequence[context["run_target_id"]] += 1
                candidates = files_by_key.get((app_id, page), [])
                offset = file_offsets[(app_id, page)]
                raw_path = candidates[offset] if offset < len(candidates) else None
                if raw_path:
                    file_offsets[(app_id, page)] += 1
                status = str(row["status"])
                success = status in {"ok", "empty_page"}
                requested_at = _timestamp_from_name(raw_path) if raw_path else execution_time + timedelta(microseconds=index)
                request_url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json?l={language}"
                cur.execute("""
                    INSERT INTO collection_requests(run_target_id, request_sequence, page_number, request_url,
                        requested_at, success, status_category, raw_review_count, distinct_review_count,
                        distinct_from_previous_page, http_status_code)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING request_id
                """, (context["run_target_id"], request_sequence[context["run_target_id"]], page, request_url,
                      requested_at, success, status, int(_value(row.get("raw_review_count")) or 0),
                      int(_value(row.get("distinct_review_count")) or 0), _value(row.get("distinct_from_previous_page")),
                      200 if success else None))
                request_id = cur.fetchone()[0]
                if raw_path:
                    request_by_file[raw_path] = request_id
                if status != "ok":
                    cur.execute("""
                        INSERT INTO missing_or_excluded_records(run_target_id, request_id, reason_code,
                            expected_count, observed_count, source_context)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (context["run_target_id"], request_id, status,
                          context["target_limit"], context["collected"], Jsonb({"page": page})))

            identities: dict[tuple[Any, str], Any] = {}
            normalized_count = repeated_count = non_review_count = 0
            for raw_path in raw_files:
                request_id = request_by_file.get(raw_path)
                if request_id is None:
                    raise ValueError(f"No request evidence matched raw payload {raw_path}")
                payload = json.loads(raw_path.read_text(encoding="utf-8"))
                payload_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
                captured_at = _timestamp_from_name(raw_path)
                cur.execute("""
                    INSERT INTO raw_payloads(request_id, storage_path, payload_sha256, payload_json, captured_at)
                    VALUES (%s,%s,%s,%s,%s) RETURNING payload_id
                """, (request_id, str(raw_path), payload_hash, Jsonb(payload), captured_at))
                payload_id = cur.fetchone()[0]
                cur.execute("""SELECT rt.app_storefront_id, sa.source_app_identifier, s.country_code, s.language_code, cr.page_number
                    FROM collection_requests cr JOIN run_targets rt ON rt.run_target_id=cr.run_target_id
                    JOIN app_storefronts ast ON ast.app_storefront_id=rt.app_storefront_id
                    JOIN source_apps sa ON sa.source_app_id=ast.source_app_id
                    JOIN storefronts s ON s.storefront_id=ast.storefront_id WHERE cr.request_id=%s""", (request_id,))
                app_storefront_id, app_id, country, language, page = cur.fetchone()
                for ordinal, entry, review_id, parse_status in _raw_entries(payload):
                    cur.execute("""
                        INSERT INTO raw_review_records(payload_id, source_review_id, record_ordinal, raw_record_json,
                            raw_record_sha256, parse_status)
                        VALUES (%s,%s,%s,%s,%s,%s) RETURNING raw_record_id
                    """, (payload_id, review_id, ordinal, Jsonb(entry), canonical_hash(entry), parse_status))
                    raw_record_id = cur.fetchone()[0]
                    if parse_status == "non_review_entry":
                        non_review_count += 1
                        cur.execute("INSERT INTO review_observations(raw_record_id, observation_status, observed_at) VALUES (%s,'non_review_entry',%s)",
                                    (raw_record_id, captured_at))
                        continue
                    identity_key = (app_storefront_id, review_id)
                    if identity_key not in identities:
                        cur.execute("""
                            INSERT INTO review_identities(app_storefront_id, source_review_id, first_seen_at, latest_seen_at)
                            VALUES (%s,%s,%s,%s)
                            ON CONFLICT(app_storefront_id, source_review_id) DO UPDATE
                            SET latest_seen_at=GREATEST(review_identities.latest_seen_at, EXCLUDED.latest_seen_at)
                            RETURNING review_identity_id
                        """, (app_storefront_id, review_id, captured_at, captured_at))
                        identities[identity_key] = cur.fetchone()[0]
                    identity_id = identities[identity_key]
                    normalized = normalized_lookup.get((str(app_id), country, language, str(review_id), int(page)))
                    if normalized is not None:
                        normalized_lookup.pop((str(app_id), country, language, str(review_id), int(page)))
                        cur.execute("""
                            INSERT INTO normalized_reviews(raw_record_id, source_review_id, review_title, review_text,
                                rating, review_date, author_id, author_name, helpful_votes, app_version,
                                developer_response, developer_response_date, source_url, raw_page_number, raw_cursor,
                                collected_at, normalized_json, normalized_hash)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING normalized_review_id
                        """, (raw_record_id, normalized["review_id"], normalized["review_title"], normalized["review_text"],
                              normalized["rating"], normalized["review_date"], normalized["author_id"], normalized["author_name"],
                              normalized["helpful_votes"], normalized["app_version"], normalized["developer_response"],
                              normalized["developer_response_date"], normalized["source_url"], normalized["raw_page_number"],
                              normalized["raw_cursor"], normalized["collected_at"], Jsonb(normalized), canonical_hash(normalized)))
                        normalized_id = cur.fetchone()[0]
                        cur.execute("""INSERT INTO review_observations(review_identity_id, raw_record_id,
                            normalized_review_id, observation_status, observed_at) VALUES (%s,%s,%s,'new',%s)""",
                                    (identity_id, raw_record_id, normalized_id, captured_at))
                        normalized_count += 1
                        if not normalized["review_title"]:
                            cur.execute("INSERT INTO quality_flags(normalized_review_id,flag_type,severity) VALUES (%s,'missing_review_title','warning')", (normalized_id,))
                        if len(str(normalized["review_text"] or "")) < 15:
                            cur.execute("INSERT INTO quality_flags(normalized_review_id,flag_type,severity) VALUES (%s,'low_signal_review','info')", (normalized_id,))
                    else:
                        cur.execute("""INSERT INTO review_observations(review_identity_id,raw_record_id,
                            observation_status,observed_at) VALUES (%s,%s,'duplicate_skipped',%s)""",
                                    (identity_id, raw_record_id, captured_at))
                        repeated_count += 1

            if normalized_lookup:
                raise ValueError(f"{len(normalized_lookup)} normalized rows could not be matched to raw records")
            for context in contexts.values():
                if context["target_limit"] is not None and context["collected"] < context["target_limit"] and not target_reached:
                    cur.execute("""INSERT INTO missing_or_excluded_records(run_target_id,reason_code,
                        expected_count,observed_count) VALUES (%s,'target_limit_not_reached',%s,%s)""",
                                (context["run_target_id"], context["target_limit"], context["collected"]))
        conn.commit()
    return reconcile_run(database_url, run_name) | {"repeated_observations": repeated_count, "non_review_entries": non_review_count}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name", choices=["apple-small-500", "apple-large-10000"])
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--report")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    result = load_apple_validation_run(args.database_url, args.run_name)
    output = json.dumps(result, indent=2, default=str)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
