from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from src.apple_live_persistence import LiveAppleSettings, run_live_apple_persistence
from src.database_load import load_apple_validation_run
from src.http_utils import HttpResult
from src.models import RequestRecord


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.postgresql


@pytest.fixture(scope="module")
def database_url() -> str:
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return DATABASE_URL


def _alembic(database_url: str, *args: str) -> None:
    env = os.environ | {"DATABASE_URL": database_url}
    subprocess.run(["alembic", *args], cwd=ROOT, env=env, check=True)


def test_upgrade_inspect_downgrade_reupgrade_and_load(database_url: str) -> None:
    _alembic(database_url, "downgrade", "base")
    _alembic(database_url, "upgrade", "head")
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] == "0002_integration_readiness"
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        assert cur.fetchone()[0] >= 16

    _alembic(database_url, "downgrade", "base")
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.normalized_reviews')")
        assert cur.fetchone()[0] is None
    _alembic(database_url, "upgrade", "head")

    result = load_apple_validation_run(database_url, "apple-small-500", ROOT)
    assert result["normalized_reviews"] == 500
    assert result["raw_without_observation"] == 0
    assert result["normalized_without_observation"] == 0
    assert result["lineage_conflicts"] == 0


def test_constraints_lineage_and_identical_payload_hashes(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT run_target_id FROM run_targets LIMIT 1")
        target_id = cur.fetchone()[0]
        cur.execute("SELECT coalesce(max(request_sequence),0)+1 FROM collection_requests WHERE run_target_id=%s", (target_id,))
        sequence = cur.fetchone()[0]
        cur.execute("""INSERT INTO collection_requests(run_target_id,request_sequence,request_url,success,status_category)
            VALUES (%s,%s,'test://one',true,'empty_page') RETURNING request_id""", (target_id, sequence))
        request_one = cur.fetchone()[0]
        cur.execute("""INSERT INTO collection_requests(run_target_id,request_sequence,request_url,success,status_category)
            VALUES (%s,%s,'test://two',true,'empty_page') RETURNING request_id""", (target_id, sequence + 1))
        request_two = cur.fetchone()[0]
        digest = "a" * 64
        cur.execute("INSERT INTO raw_payloads(request_id,payload_sha256,payload_json) VALUES (%s,%s,'{}')", (request_one, digest))
        cur.execute("INSERT INTO raw_payloads(request_id,payload_sha256,payload_json) VALUES (%s,%s,'{}')", (request_two, digest))
        cur.execute("SELECT payload_id FROM raw_payloads WHERE request_id=%s", (request_one,))
        payload_one = cur.fetchone()[0]
        cur.execute("""INSERT INTO raw_review_records(payload_id,record_ordinal,raw_record_json,raw_record_sha256,
            parse_status,parse_error) VALUES (%s,0,'{}',%s,'parse_error','invalid entry') RETURNING raw_record_id""",
                    (payload_one, "b" * 64))
        parse_error_raw = cur.fetchone()[0]
        cur.execute("INSERT INTO review_observations(raw_record_id,observation_status) VALUES (%s,'parse_error')", (parse_error_raw,))

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                cur.execute("""INSERT INTO collection_requests(run_target_id,request_sequence,request_url,success,
                    status_category,raw_review_count,distinct_review_count)
                    VALUES (%s,%s,'test://bad',true,'request_failed',0,1)""", (target_id, sequence + 2))

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                cur.execute("INSERT INTO quality_flags(flag_type,severity) VALUES ('bad','warning')")

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                cur.execute("""INSERT INTO collection_requests(run_target_id,request_sequence,request_url,success,status_category)
                    VALUES ('00000000-0000-0000-0000-000000000000',999,'test://fk',true,'empty_page')""")

        cur.execute("""SELECT ro.observation_id, other.review_identity_id
            FROM review_observations ro
            JOIN review_identities current_identity USING(review_identity_id)
            JOIN review_identities other ON other.app_storefront_id <> current_identity.app_storefront_id
            WHERE ro.review_identity_id IS NOT NULL LIMIT 1""")
        observation_id, wrong_identity_id = cur.fetchone()
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                cur.execute("UPDATE review_observations SET review_identity_id=%s WHERE observation_id=%s",
                            (wrong_identity_id, observation_id))


def test_standalone_postgresql_ddl_executes(database_url: str) -> None:
    ddl = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS ddl_validation CASCADE")
        cur.execute("CREATE SCHEMA ddl_validation")
        cur.execute("SET search_path TO ddl_validation, public")
        cur.execute(ddl)
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='ddl_validation'")
        assert cur.fetchone()[0] == 15
        cur.execute("DROP SCHEMA ddl_validation CASCADE")


def test_all_example_and_reconciliation_queries_execute(database_url: str) -> None:
    sql = (ROOT / "docs" / "database_example_queries.sql").read_text(encoding="utf-8")
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement.replace(":source_review_id", "'not-present'"))
            if cur.description:
                cur.fetchall()


def test_mocked_live_persistence_preserves_all_appearances_and_repeats(database_url: str, tmp_path: Path) -> None:
    payload = {"feed": {"entry": [
        {"id": {"label": "app-metadata"}},
        {
            "id": {"label": "live-review-1"}, "title": {"label": "Good"},
            "content": {"label": "A useful review body."}, "im:rating": {"label": "5"},
            "updated": {"label": "2026-07-17T00:00:00Z"}, "author": {"name": {"label": "One"}},
        },
        {
            "id": {"label": "live-review-2"}, "title": {"label": "Fine"},
            "content": {"label": "Another useful review."}, "im:rating": {"label": "4"},
            "updated": {"label": "2026-07-17T00:00:00Z"}, "author": {"name": {"label": "Two"}},
        },
        "malformed-entry",
    ]}}
    session = _FakeAppleSession(payload, repeats=2)
    settings = LiveAppleSettings(
        database_url=database_url, output_root=tmp_path, run_name="apple-live-postgresql-test",
        passes=2, max_pages_per_pass=1, max_requests=2, max_normalized_reviews=1,
    )

    report = run_live_apple_persistence(settings, session=session)

    assert report["apps"] == 1
    assert report["storefronts"] == 1
    assert report["targets"] == 1
    assert report["requests"] == 2
    assert report["payloads"] == 2
    assert report["raw_review_appearances"] == 8
    assert report["normalized_reviews"] == 1
    assert report["observation_statuses"] == {
        "excluded": 1, "new": 1, "non_review_entry": 2, "parse_error": 2, "repeat_seen": 2,
    }
    assert report["duplicate_or_repeated_observations"] == 2
    assert report["request_statuses"] == {"ok": 2}
    assert report["incomplete_categories"] == {"normalization_cap_exceeded": 1}
    assert report["failed_pages"] == 0
    assert report["empty_pages"] == 0
    assert report["malformed_pages"] == 0
    assert report["limited_or_incomplete_pages"] == 1
    assert report["reconciliation_issues"] == {}
    assert report["integrity_issue_count"] == 0
    assert report["final_run_status"] == "completed"
    assert (tmp_path / "reports" / "apple_live" / settings.run_name / "live_persistence_report.json").exists()
    assert len(list((tmp_path / "data" / "raw" / "apple_live" / settings.run_name).glob("*.json"))) == 2

    with pytest.raises(FileExistsError):
        run_live_apple_persistence(settings, session=_FakeAppleSession(payload, repeats=2))


class _FakeAppleSession:
    def __init__(self, payload: dict, repeats: int) -> None:
        self.content = json.dumps(payload).encode()
        self.remaining = repeats

    def get(self, url: str) -> HttpResult:
        assert self.remaining > 0
        self.remaining -= 1

        class Response:
            status_code = 200
            headers = {"content-type": "application/json"}

            def __init__(self, content: bytes) -> None:
                self.content = content

        return HttpResult(Response(self.content), RequestRecord(
            url=url, status_code=200, elapsed_seconds=0.01, success=True,
            content_type="application/json", response_size=len(self.content),
        ))
