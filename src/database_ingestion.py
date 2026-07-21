"""Reusable PostgreSQL persistence primitives for review ingestion."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def raw_apple_entries(payload: dict[str, Any]) -> list[tuple[int, Any, str | None, str, str | None]]:
    """Return every feed appearance, including malformed and metadata entries."""
    entries = payload.get("feed", {}).get("entry", []) if isinstance(payload.get("feed", {}), dict) else []
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return [(0, entries, None, "parse_error", "feed.entry is not a list or object")]
    result = []
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            result.append((ordinal, entry, None, "parse_error", "feed entry is not an object"))
            continue
        review_id = entry.get("id", {}).get("label") if isinstance(entry.get("id"), dict) else None
        if "im:rating" in entry and review_id not in (None, ""):
            result.append((ordinal, entry, str(review_id), "parsed", None))
        elif "im:rating" in entry:
            result.append((ordinal, entry, None, "parse_error", "review entry has no source review id"))
        else:
            result.append((ordinal, entry, None, "non_review_entry", None))
    return result


class IngestionStore:
    """Schema-compatible writes shared by historical and live ingestion adapters."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn

    def ensure_apple_source(self) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO review_sources(source_code, display_name, priority, access_method,
                    access_method_type, is_primary, limitations)
                VALUES ('apple_app_store', 'Apple App Store', 1, 'Customer Reviews RSS JSON',
                    'publicly accessible undocumented feed', true, %s)
                ON CONFLICT (source_code) DO UPDATE SET display_name=EXCLUDED.display_name
                RETURNING source_id
            """, (["RSS page-depth is limited", "Endpoint is undocumented"],))
            return cur.fetchone()[0]

    def create_run(self, external_run_name: str, phase: str, target_review_count: int,
                   config: dict[str, Any], raw_path: Path, report_path: Path) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingestion_runs(external_run_name, phase, status, target_review_count,
                    config, raw_output_path, reports_output_path)
                VALUES (%s,%s,'running',%s,%s,%s,%s) RETURNING run_id
            """, (external_run_name, phase, target_review_count, Jsonb(config), str(raw_path), str(report_path)))
            return cur.fetchone()[0]

    def resolve_target(self, source_id: Any, run_id: Any, *, app_id: str, app_name: str,
                       country: str, language: str, category: str | None,
                       target_review_count: int, max_pages: int) -> tuple[Any, Any]:
        app_storefront_id = self.resolve_app_storefront(
            source_id, app_id=app_id, app_name=app_name, country=country,
            language=language, category=category,
        )
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO run_targets(run_id,app_storefront_id,target_review_count,max_pages,status)
                VALUES (%s,%s,%s,%s,'running') RETURNING run_target_id""",
                        (run_id, app_storefront_id, target_review_count, max_pages))
            return cur.fetchone()[0], app_storefront_id

    def resolve_app_storefront(self, source_id: Any, *, app_id: str, app_name: str,
                               country: str, language: str, category: str | None) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("SELECT source_app_id, app_id FROM source_apps WHERE source_id=%s AND source_app_identifier=%s",
                        (source_id, app_id))
            existing = cur.fetchone()
            if existing:
                source_app_id, canonical_app_id = existing
                cur.execute("UPDATE apps SET canonical_name=%s,category=%s WHERE app_id=%s",
                            (app_name, category, canonical_app_id))
            else:
                cur.execute("INSERT INTO apps(canonical_name,category) VALUES (%s,%s) RETURNING app_id",
                            (app_name, category))
                canonical_app_id = cur.fetchone()[0]
                cur.execute("""INSERT INTO source_apps(source_id,app_id,source_app_identifier)
                    VALUES (%s,%s,%s) RETURNING source_app_id""", (source_id, canonical_app_id, app_id))
                source_app_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO storefronts(country_code,language_code) VALUES (%s,%s)
                ON CONFLICT(country_code,language_code) DO UPDATE SET country_code=EXCLUDED.country_code
                RETURNING storefront_id""", (country, language))
            storefront_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO app_storefronts(source_app_id,storefront_id,configured_category)
                VALUES (%s,%s,%s) ON CONFLICT(source_app_id,storefront_id)
                DO UPDATE SET configured_category=COALESCE(EXCLUDED.configured_category,app_storefronts.configured_category)
                RETURNING app_storefront_id""", (source_app_id, storefront_id, category))
            app_storefront_id = cur.fetchone()[0]
            return app_storefront_id

    def add_request(self, run_target_id: Any, sequence: int, page: int, url: str, record: Any,
                    status: str, raw_count: int, distinct_count: int, requested_at: datetime,
                    completed_at: datetime) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO collection_requests(run_target_id,request_sequence,page_number,request_url,
                requested_at,completed_at,elapsed_seconds,http_status_code,success,blocked,content_type,
                response_size_bytes,error_message,status_category,raw_review_count,distinct_review_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING request_id""",
                (run_target_id, sequence, page, url, requested_at, completed_at, record.elapsed_seconds,
                 record.status_code, status in {"ok", "empty_page"}, bool(record.blocked), record.content_type,
                 record.response_size, record.error, status, raw_count, distinct_count))
            return cur.fetchone()[0]

    def add_payload(self, request_id: Any, raw_path: Path, content: bytes,
                    payload: dict[str, Any] | None, captured_at: datetime) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO raw_payloads(request_id,storage_path,payload_sha256,payload_json,captured_at)
                VALUES (%s,%s,%s,%s,%s) RETURNING payload_id""",
                (request_id, str(raw_path), hashlib.sha256(content).hexdigest(), Jsonb(payload) if payload is not None else None,
                 captured_at))
            return cur.fetchone()[0]

    def add_raw_record(self, payload_id: Any, ordinal: int, entry: Any, review_id: str | None,
                       parse_status: str, parse_error: str | None) -> Any:
        raw_json = entry if isinstance(entry, (dict, list, str, int, float, bool)) or entry is None else str(entry)
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO raw_review_records(payload_id,source_review_id,record_ordinal,
                raw_record_json,raw_record_sha256,parse_status,parse_error)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING raw_record_id""",
                (payload_id, review_id, ordinal, Jsonb(raw_json), canonical_hash(raw_json), parse_status, parse_error))
            return cur.fetchone()[0]

    def add_non_normalized_observation(self, raw_record_id: Any, status: str, observed_at: datetime,
                                       identity_id: Any = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO review_observations(review_identity_id,raw_record_id,observation_status,observed_at)
                VALUES (%s,%s,%s,%s)""", (identity_id, raw_record_id, status, observed_at))

    def resolve_identity(self, app_storefront_id: Any, review_id: str, observed_at: datetime) -> tuple[Any, bool]:
        with self.conn.cursor() as cur:
            cur.execute("""SELECT review_identity_id FROM review_identities
                WHERE app_storefront_id=%s AND source_review_id=%s""", (app_storefront_id, review_id))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE review_identities SET latest_seen_at=GREATEST(latest_seen_at,%s) WHERE review_identity_id=%s",
                            (observed_at, row[0]))
                return row[0], False
            cur.execute("""INSERT INTO review_identities(app_storefront_id,source_review_id,first_seen_at,latest_seen_at)
                VALUES (%s,%s,%s,%s) RETURNING review_identity_id""",
                        (app_storefront_id, review_id, observed_at, observed_at))
            return cur.fetchone()[0], True

    def add_normalized(self, raw_record_id: Any, identity_id: Any, review: dict[str, Any],
                       observed_at: datetime) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO normalized_reviews(raw_record_id,source_review_id,review_title,review_text,
                rating,review_date,author_id,author_name,helpful_votes,app_version,developer_response,
                developer_response_date,source_url,raw_page_number,raw_cursor,collected_at,normalized_json,normalized_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING normalized_review_id""",
                (raw_record_id, review.get("review_id"), review.get("review_title"), review.get("review_text"),
                 review.get("rating"), review.get("review_date"), review.get("author_id"), review.get("author_name"),
                 review.get("helpful_votes"), review.get("app_version"), review.get("developer_response"),
                 review.get("developer_response_date"), review.get("source_url"), review.get("raw_page_number"),
                 review.get("raw_cursor"), review.get("collected_at") or observed_at, Jsonb(review), canonical_hash(review)))
            normalized_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO review_observations(review_identity_id,raw_record_id,normalized_review_id,
                observation_status,observed_at) VALUES (%s,%s,%s,'new',%s)""",
                        (identity_id, raw_record_id, normalized_id, observed_at))
            if not review.get("review_title"):
                cur.execute("INSERT INTO quality_flags(normalized_review_id,flag_type,severity) VALUES (%s,'missing_review_title','warning')",
                            (normalized_id,))
            if len(str(review.get("review_text") or "")) < 15:
                cur.execute("INSERT INTO quality_flags(normalized_review_id,flag_type,severity) VALUES (%s,'low_signal_review','info')",
                            (normalized_id,))
            return normalized_id

    def add_missing_evidence(self, run_target_id: Any, reason: str, request_id: Any = None,
                             expected: int | None = None, observed: int | None = None,
                             detail: str | None = None, context: dict[str, Any] | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO missing_or_excluded_records(run_target_id,request_id,reason_code,
                reason_detail,expected_count,observed_count,source_context) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (run_target_id, request_id, reason, detail, expected, observed, Jsonb(context or {})))

    def finalize(self, run_id: Any, run_target_id: Any, normalized_count: int, target_reached: bool,
                 status: str, stop_reason: str | None) -> None:
        completed_at = utc_now()
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE run_targets SET reviews_collected=%s,status=%s,stop_reason=%s
                WHERE run_target_id=%s""", (normalized_count, status, stop_reason, run_target_id))
            cur.execute("""UPDATE ingestion_runs SET completed_at=%s,status=%s,reviews_collected=%s,
                target_reached=%s,stop_reason=%s WHERE run_id=%s""",
                (completed_at, status, normalized_count, target_reached, stop_reason, run_id))


def reconcile_run(database_url: str, run_name: str) -> dict[str, Any]:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("""SELECT r.status, count(DISTINCT a.app_id), count(DISTINCT s.storefront_id),
            count(DISTINCT rt.run_target_id), count(DISTINCT cr.request_id), count(DISTINCT rp.payload_id),
            count(DISTINCT rrr.raw_record_id), count(DISTINCT nr.normalized_review_id),
            count(DISTINCT ro.observation_id), count(DISTINCT qf.quality_flag_id), count(DISTINCT mer.missing_record_id)
            FROM ingestion_runs r LEFT JOIN run_targets rt USING(run_id)
            LEFT JOIN app_storefronts ast USING(app_storefront_id) LEFT JOIN source_apps sa USING(source_app_id)
            LEFT JOIN apps a USING(app_id) LEFT JOIN storefronts s USING(storefront_id)
            LEFT JOIN collection_requests cr USING(run_target_id) LEFT JOIN raw_payloads rp USING(request_id)
            LEFT JOIN raw_review_records rrr USING(payload_id) LEFT JOIN normalized_reviews nr USING(raw_record_id)
            LEFT JOIN review_observations ro USING(raw_record_id)
            LEFT JOIN quality_flags qf ON qf.normalized_review_id=nr.normalized_review_id OR qf.raw_record_id=rrr.raw_record_id OR qf.request_id=cr.request_id
            LEFT JOIN missing_or_excluded_records mer USING(run_target_id)
            WHERE r.external_run_name=%s GROUP BY r.status""", (run_name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Ingestion run not found: {run_name}")
        names = ["final_run_status", "apps", "storefronts", "targets", "requests", "payloads", "raw_review_appearances",
                 "normalized_reviews", "observations", "quality_flags", "missing_evidence"]
        result = dict(zip(names, row))
        checks = {
            "raw_without_observation": """SELECT count(*) FROM raw_review_records rrr JOIN raw_payloads rp USING(payload_id)
                JOIN collection_requests cr USING(request_id) JOIN run_targets rt USING(run_target_id)
                JOIN ingestion_runs r USING(run_id) LEFT JOIN review_observations ro USING(raw_record_id)
                WHERE r.external_run_name=%s AND ro.observation_id IS NULL""",
            "normalized_without_observation": """SELECT count(*) FROM normalized_reviews nr JOIN raw_review_records rrr USING(raw_record_id)
                JOIN raw_payloads rp USING(payload_id) JOIN collection_requests cr USING(request_id)
                JOIN run_targets rt USING(run_target_id) JOIN ingestion_runs r USING(run_id)
                LEFT JOIN review_observations ro USING(normalized_review_id)
                WHERE r.external_run_name=%s AND ro.observation_id IS NULL""",
            "lineage_conflicts": """SELECT count(*) FROM review_observations ro JOIN raw_review_records rrr USING(raw_record_id)
                JOIN raw_payloads rp USING(payload_id) JOIN collection_requests cr USING(request_id)
                JOIN run_targets rt USING(run_target_id) LEFT JOIN review_identities ri USING(review_identity_id)
                JOIN ingestion_runs r USING(run_id) WHERE r.external_run_name=%s
                AND ri.review_identity_id IS NOT NULL AND ri.app_storefront_id<>rt.app_storefront_id""",
        }
        for name, sql in checks.items():
            cur.execute(sql, (run_name,)); result[name] = cur.fetchone()[0]
        for key, table, column in (("observation_statuses", "review_observations", "observation_status"),
                                   ("request_statuses", "collection_requests", "status_category"),
                                   ("scope_or_exclusion_categories", "missing_or_excluded_records", "reason_code")):
            join = "JOIN raw_review_records rrr USING(raw_record_id) JOIN raw_payloads rp USING(payload_id) JOIN collection_requests cr USING(request_id) JOIN run_targets rt USING(run_target_id)" if table == "review_observations" else "JOIN run_targets rt USING(run_target_id)"
            cur.execute(f"""SELECT {column},count(*) FROM {table} {join} JOIN ingestion_runs r USING(run_id)
                WHERE r.external_run_name=%s GROUP BY {column}""", (run_name,))
            result[key] = dict(cur.fetchall())
        result["duplicate_or_repeated_observations"] = sum(result["observation_statuses"].get(k, 0) for k in ("repeat_seen", "duplicate_skipped"))
        result["failed_pages"] = result["request_statuses"].get("request_failed", 0)
        result["empty_pages"] = result["request_statuses"].get("empty_page", 0)
        result["malformed_pages"] = result["request_statuses"].get("json_parse_error", 0)
        result["limited_pages"] = result["request_statuses"].get("pagination_limit_or_unavailable_page", 0)
        result["collection_issue_pages"] = sum(
            result[name] for name in ("failed_pages", "empty_pages", "malformed_pages", "limited_pages")
        )
        cur.execute("""SELECT count(DISTINCT mer.request_id) FROM missing_or_excluded_records mer
            JOIN run_targets rt USING(run_target_id) JOIN ingestion_runs r USING(run_id)
            WHERE r.external_run_name=%s AND mer.request_id IS NOT NULL
            AND mer.reason_code IN ('normalization_cap_exceeded','request_limit_reached','configured_scope_exhausted')""",
            (run_name,))
        result["scope_limited_pages"] = cur.fetchone()[0]
        result["reconciliation_issues"] = {name: result[name] for name in checks if result[name]}
        result["integrity_issue_count"] = sum(result[k] for k in checks)
        result["raw_records"] = result["raw_review_appearances"]
        return result
