from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from src.database_load import load_apple_validation_run


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
