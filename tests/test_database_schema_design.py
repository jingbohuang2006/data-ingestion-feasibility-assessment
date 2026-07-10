from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"
MIGRATION = ROOT / "alembic" / "versions" / "0001_initial_review_ingestion_schema.py"
DESIGN_DOC = ROOT / "docs" / "database_schema_design.md"
FIELD_MAPPING_DOC = ROOT / "docs" / "database_field_mapping.md"
QUERY_DOC = ROOT / "docs" / "database_example_queries.sql"
README = ROOT / "README.md"


REQUIRED_TABLES = {
    "review_sources",
    "apps",
    "source_apps",
    "storefronts",
    "app_storefronts",
    "ingestion_runs",
    "run_targets",
    "collection_requests",
    "raw_payloads",
    "raw_review_records",
    "normalized_reviews",
    "review_identities",
    "review_observations",
    "quality_flags",
    "missing_or_excluded_records",
}


def test_schema_defines_required_tables() -> None:
    ddl = _read(SCHEMA_SQL)
    defined_tables = set(re.findall(r"CREATE TABLE ([a-z_]+)", ddl))

    assert REQUIRED_TABLES <= defined_tables


def test_schema_preserves_raw_payloads_in_jsonb_and_filesystem_with_hashes() -> None:
    ddl = _read(SCHEMA_SQL)
    raw_payloads = _table_block(ddl, "raw_payloads")
    raw_records = _table_block(ddl, "raw_review_records")
    normalized = _table_block(ddl, "normalized_reviews")

    assert "storage_path text" in raw_payloads
    assert "payload_json jsonb" in raw_payloads
    assert "payload_sha256 text NOT NULL" in raw_payloads
    assert "raw_record_sha256 text NOT NULL" in raw_records
    assert "normalized_hash text NOT NULL" in normalized
    assert "raw_payloads_storage_or_json" in raw_payloads
    assert "^[0-9a-f]{64}$" in raw_payloads


def test_review_identity_is_scoped_by_source_app_storefront_and_review_id() -> None:
    ddl = _read(SCHEMA_SQL)
    identities = _table_block(ddl, "review_identities")

    assert "source_id uuid NOT NULL REFERENCES review_sources" in identities
    assert "app_storefront_id uuid NOT NULL REFERENCES app_storefronts" in identities
    assert "source_review_id text NOT NULL" in identities
    assert "UNIQUE (source_id, app_storefront_id, source_review_id)" in identities


def test_request_evidence_statuses_cover_failures_empty_pages_and_wrapper_limits() -> None:
    ddl = _read(SCHEMA_SQL)
    requests = _table_block(ddl, "collection_requests")

    for status in {
        "ok",
        "empty_page",
        "request_failed",
        "pagination_limit_or_unavailable_page",
        "json_parse_error",
        "target_limit_not_reached",
        "wrapper_evidence_incomplete",
        "skipped",
    }:
        assert f"'{status}'" in requests
    assert "http_status_code integer" in requests
    assert "error_message text" in requests
    assert "raw_review_count integer NOT NULL DEFAULT 0" in requests


def test_traceability_foreign_key_path_is_present() -> None:
    ddl = _read(SCHEMA_SQL)

    assert "run_id uuid NOT NULL REFERENCES ingestion_runs" in _table_block(ddl, "run_targets")
    assert "run_target_id uuid NOT NULL REFERENCES run_targets" in _table_block(ddl, "collection_requests")
    assert "request_id uuid NOT NULL REFERENCES collection_requests" in _table_block(ddl, "raw_payloads")
    assert "request_id uuid NOT NULL REFERENCES collection_requests" in _table_block(ddl, "raw_review_records")
    assert "raw_record_id uuid NOT NULL REFERENCES raw_review_records" in _table_block(ddl, "normalized_reviews")
    assert "run_id uuid NOT NULL REFERENCES ingestion_runs" in _table_block(ddl, "normalized_reviews")


def test_quality_and_missing_tables_require_actionable_context() -> None:
    ddl = _read(SCHEMA_SQL)
    quality = _table_block(ddl, "quality_flags")
    missing = _table_block(ddl, "missing_or_excluded_records")

    assert "quality_flags_has_subject" in quality
    assert "severity IN ('info', 'warning', 'error')" in quality
    assert "run_target_id uuid NOT NULL REFERENCES run_targets" in missing
    assert "reason_code text NOT NULL" in missing
    assert "source_context jsonb NOT NULL DEFAULT '{}'::jsonb" in missing


def test_indexes_cover_expected_analysis_paths() -> None:
    ddl = _read(SCHEMA_SQL)

    expected_indexes = {
        "ix_collection_requests_target_page",
        "ix_collection_requests_status_category",
        "ix_normalized_reviews_app_date",
        "ix_normalized_reviews_source_review_id",
        "ix_review_observations_status",
        "ix_quality_flags_type_severity",
        "ix_missing_records_reason_code",
    }

    for index_name in expected_indexes:
        assert index_name in ddl


def test_alembic_migration_represents_initial_schema() -> None:
    migration = _read(MIGRATION)

    assert 'revision = "0001_initial_review_ingestion_schema"' in migration
    assert "down_revision = None" in migration
    for table in REQUIRED_TABLES:
        assert f"CREATE TABLE {table}" in migration
    assert "DROP TABLE IF EXISTS review_sources" in migration


def test_documentation_covers_stage_boundaries_and_google_play_limitation() -> None:
    readme = _read(README)
    design_doc = _read(DESIGN_DOC)

    assert "does not connect to or persist into a live database yet" in readme
    assert "This stage defines the proposed PostgreSQL schema" in design_doc
    assert "does not connect the existing collection pipeline to a live database" in design_doc
    assert "Google Play remains a secondary benchmark" in design_doc
    assert "does not expose complete HTTP-level request evidence" in design_doc
    assert "This stage intentionally does not load the current 6,396-review validation run" in design_doc


def test_field_mapping_links_current_outputs_to_database_tables() -> None:
    mapping = _read(FIELD_MAPPING_DOC)

    assert "apple_app_store_validation_reviews.csv" in mapping
    assert "pagination_depth_and_failures.csv" in mapping
    assert "raw_payloads.storage_path" in mapping
    assert "raw_payloads.payload_json" in mapping
    assert "collection_requests.http_status_code" in mapping
    assert "status_category = 'wrapper_evidence_incomplete'" in mapping


def test_example_queries_cover_required_analysis_questions() -> None:
    queries = _read(QUERY_DOC)

    expected_headings = {
        "Failed requests",
        "Empty pages",
        "Unavailable pages or pagination limits",
        "App/storefront-level shortfalls",
        "Duplicate and repeated review observations",
        "Missing or excluded records",
        "Raw-to-normalized traceability",
    }
    for heading in expected_headings:
        assert heading in queries

    assert "WHERE cr.status_category = 'empty_page'" in queries
    assert "WHERE cr.status_category = 'pagination_limit_or_unavailable_page'" in queries
    assert "WHERE nr.source_review_id = :source_review_id" in queries


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _table_block(ddl: str, table_name: str) -> str:
    match = re.search(rf"CREATE TABLE {table_name} \((.*?)\n\);", ddl, flags=re.DOTALL)
    assert match is not None, f"Could not find CREATE TABLE block for {table_name}"
    return match.group(1)
