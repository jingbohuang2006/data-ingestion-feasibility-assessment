"""Enforce integration-safe lineage and evidence constraints.

Revision ID: 0002_integration_readiness
Revises: 0001_initial
Create Date: 2026-07-14
"""
from __future__ import annotations

from alembic import op


revision = "0002_integration_readiness"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE run_targets ADD CONSTRAINT run_targets_status_valid
            CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed', 'skipped'));

        DROP INDEX ix_collection_requests_source_status;
        ALTER TABLE collection_requests DROP COLUMN source_id;
        ALTER TABLE collection_requests
            ADD CONSTRAINT collection_requests_distinct_lte_raw CHECK (distinct_review_count <= raw_review_count),
            ADD CONSTRAINT collection_requests_completed_order CHECK (completed_at IS NULL OR completed_at >= requested_at),
            ADD CONSTRAINT collection_requests_outcome_consistent CHECK (
                (success AND status_category IN ('ok', 'empty_page')) OR
                (NOT success AND status_category NOT IN ('ok', 'empty_page'))
            );
        CREATE INDEX ix_collection_requests_http_status ON collection_requests (http_status_code);

        DROP INDEX uq_raw_payloads_payload_sha256;
        ALTER TABLE raw_payloads ADD CONSTRAINT uq_raw_payloads_request UNIQUE (request_id);
        CREATE INDEX ix_raw_payloads_payload_sha256 ON raw_payloads (payload_sha256);

        ALTER TABLE raw_review_records DROP CONSTRAINT uq_raw_review_records_request_ordinal;
        ALTER TABLE raw_review_records DROP COLUMN request_id;
        ALTER TABLE raw_review_records ALTER COLUMN payload_id SET NOT NULL;
        ALTER TABLE raw_review_records DROP CONSTRAINT raw_review_records_payload_id_fkey;
        ALTER TABLE raw_review_records ADD CONSTRAINT raw_review_records_payload_id_fkey
            FOREIGN KEY (payload_id) REFERENCES raw_payloads(payload_id) ON DELETE CASCADE;
        ALTER TABLE raw_review_records
            ADD CONSTRAINT raw_review_records_parse_error_consistent CHECK (
                (parse_status = 'parse_error' AND parse_error IS NOT NULL) OR parse_status <> 'parse_error'
            ),
            ADD CONSTRAINT uq_raw_review_records_payload_ordinal UNIQUE (payload_id, record_ordinal);

        DROP INDEX ix_normalized_reviews_app_date;
        DROP INDEX ix_normalized_reviews_source_review_id;
        DROP INDEX ix_normalized_reviews_run_id;
        ALTER TABLE normalized_reviews DROP COLUMN run_id, DROP COLUMN app_storefront_id, DROP COLUMN source_code;
        ALTER TABLE normalized_reviews DROP CONSTRAINT normalized_reviews_raw_record_id_fkey;
        ALTER TABLE normalized_reviews ADD CONSTRAINT normalized_reviews_raw_record_id_fkey
            FOREIGN KEY (raw_record_id) REFERENCES raw_review_records(raw_record_id) ON DELETE CASCADE;
        CREATE INDEX ix_normalized_reviews_review_date ON normalized_reviews (review_date);
        CREATE INDEX ix_normalized_reviews_source_review_id ON normalized_reviews (source_review_id);

        ALTER TABLE review_identities DROP CONSTRAINT uq_review_identities_context_review;
        ALTER TABLE review_identities DROP COLUMN source_id;
        ALTER TABLE review_identities ADD CONSTRAINT uq_review_identities_context_review
            UNIQUE (app_storefront_id, source_review_id);

        DROP INDEX ix_review_observations_run_id;
        DROP INDEX ix_review_observations_request_id;
        ALTER TABLE review_observations DROP CONSTRAINT uq_review_observations_identity_run_request;
        ALTER TABLE review_observations DROP CONSTRAINT review_observations_status_valid;
        ALTER TABLE review_observations ALTER COLUMN review_identity_id DROP NOT NULL;
        ALTER TABLE review_observations DROP COLUMN run_id, DROP COLUMN request_id;
        ALTER TABLE review_observations ADD COLUMN raw_record_id uuid NOT NULL
            REFERENCES raw_review_records(raw_record_id) ON DELETE CASCADE;
        ALTER TABLE review_observations
            ADD CONSTRAINT uq_review_observations_raw_record UNIQUE (raw_record_id),
            ADD CONSTRAINT uq_review_observations_normalized UNIQUE (normalized_review_id),
            ADD CONSTRAINT review_observations_status_valid CHECK (
                observation_status IN ('new', 'repeat_seen', 'duplicate_skipped', 'excluded', 'parse_error', 'non_review_entry')
            ),
            ADD CONSTRAINT review_observations_identity_required CHECK (
                observation_status IN ('excluded', 'parse_error', 'non_review_entry') OR review_identity_id IS NOT NULL
            ),
            ADD CONSTRAINT review_observations_normalized_consistent CHECK (
                (observation_status = 'new' AND normalized_review_id IS NOT NULL) OR
                (observation_status <> 'new' AND normalized_review_id IS NULL)
            );
        CREATE INDEX ix_review_observations_identity_id ON review_observations (review_identity_id);

        ALTER TABLE quality_flags DROP CONSTRAINT quality_flags_has_subject;
        ALTER TABLE quality_flags ADD CONSTRAINT quality_flags_one_subject
            CHECK (num_nonnulls(normalized_review_id, raw_record_id, request_id) = 1);
        CREATE INDEX ix_quality_flags_raw_record_id ON quality_flags (raw_record_id);

        ALTER TABLE missing_or_excluded_records
            ADD CONSTRAINT missing_records_counts_valid CHECK (
                expected_count IS NULL OR observed_count IS NULL OR observed_count <= expected_count
            ),
            ADD CONSTRAINT missing_records_reason_nonempty CHECK (length(trim(reason_code)) > 0);

        CREATE FUNCTION enforce_review_lineage_consistency() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE raw_context uuid; identity_context uuid; normalized_raw uuid;
        BEGIN
            SELECT rt.app_storefront_id INTO raw_context
            FROM raw_review_records rrr
            JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
            JOIN collection_requests cr ON cr.request_id = rp.request_id
            JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
            WHERE rrr.raw_record_id = NEW.raw_record_id;
            IF NEW.review_identity_id IS NOT NULL THEN
                SELECT app_storefront_id INTO identity_context FROM review_identities
                WHERE review_identity_id = NEW.review_identity_id;
                IF identity_context IS DISTINCT FROM raw_context THEN
                    RAISE EXCEPTION 'review identity context does not match raw record context';
                END IF;
            END IF;
            IF NEW.normalized_review_id IS NOT NULL THEN
                SELECT raw_record_id INTO normalized_raw FROM normalized_reviews
                WHERE normalized_review_id = NEW.normalized_review_id;
                IF normalized_raw IS DISTINCT FROM NEW.raw_record_id THEN
                    RAISE EXCEPTION 'normalized review does not match observation raw record';
                END IF;
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER trg_review_lineage_consistency BEFORE INSERT OR UPDATE ON review_observations
            FOR EACH ROW EXECUTE FUNCTION enforce_review_lineage_consistency();

        CREATE FUNCTION enforce_missing_request_context() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE request_target uuid;
        BEGIN
            IF NEW.request_id IS NOT NULL THEN
                SELECT run_target_id INTO request_target FROM collection_requests WHERE request_id = NEW.request_id;
                IF request_target IS DISTINCT FROM NEW.run_target_id THEN
                    RAISE EXCEPTION 'missing/excluded request does not match run target';
                END IF;
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER trg_missing_request_context BEFORE INSERT OR UPDATE ON missing_or_excluded_records
            FOR EACH ROW EXECUTE FUNCTION enforce_missing_request_context();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER trg_missing_request_context ON missing_or_excluded_records;
        DROP FUNCTION enforce_missing_request_context();
        DROP TRIGGER trg_review_lineage_consistency ON review_observations;
        DROP FUNCTION enforce_review_lineage_consistency();
        -- This revision intentionally refuses a lossy downgrade once data exists.
        -- A clean disposable database can downgrade by dropping all schema objects
        -- through the baseline revision.
    """)
