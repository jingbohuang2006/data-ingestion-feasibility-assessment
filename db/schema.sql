-- PostgreSQL schema proposal for review ingestion evidence storage.
-- This stage is design-only: collection code does not write to this schema yet.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE review_sources (
    source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code text NOT NULL UNIQUE,
    display_name text NOT NULL,
    priority integer NOT NULL DEFAULT 100,
    access_method text,
    access_method_type text,
    is_primary boolean NOT NULL DEFAULT false,
    limitations text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT review_sources_source_code_nonempty CHECK (length(trim(source_code)) > 0)
);

CREATE TABLE apps (
    app_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name text NOT NULL,
    category text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT apps_canonical_name_nonempty CHECK (length(trim(canonical_name)) > 0)
);

CREATE INDEX ix_apps_canonical_name ON apps (canonical_name);

CREATE TABLE source_apps (
    source_app_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES review_sources (source_id) ON DELETE RESTRICT,
    app_id uuid NOT NULL REFERENCES apps (app_id) ON DELETE RESTRICT,
    source_app_identifier text NOT NULL,
    source_url text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT source_apps_identifier_nonempty CHECK (length(trim(source_app_identifier)) > 0),
    CONSTRAINT uq_source_apps_source_identifier UNIQUE (source_id, source_app_identifier)
);

CREATE INDEX ix_source_apps_app_id ON source_apps (app_id);

CREATE TABLE storefronts (
    storefront_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    country_code text NOT NULL,
    language_code text NOT NULL,
    storefront_name text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT storefronts_country_lower CHECK (country_code = lower(country_code)),
    CONSTRAINT storefronts_language_lower CHECK (language_code = lower(language_code)),
    CONSTRAINT uq_storefronts_country_language UNIQUE (country_code, language_code)
);

CREATE TABLE app_storefronts (
    app_storefront_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_app_id uuid NOT NULL REFERENCES source_apps (source_app_id) ON DELETE RESTRICT,
    storefront_id uuid NOT NULL REFERENCES storefronts (storefront_id) ON DELETE RESTRICT,
    configured_category text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_app_storefronts_source_storefront UNIQUE (source_app_id, storefront_id)
);

CREATE INDEX ix_app_storefronts_storefront_id ON app_storefronts (storefront_id);

CREATE TABLE ingestion_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_run_name text UNIQUE,
    phase text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    status text NOT NULL,
    target_review_count integer,
    reviews_collected integer NOT NULL DEFAULT 0,
    target_reached boolean,
    stop_reason text,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    code_version text,
    processed_output_path text,
    reports_output_path text,
    raw_output_path text,
    CONSTRAINT ingestion_runs_status_valid CHECK (status IN ('running', 'completed', 'partial', 'failed', 'skipped')),
    CONSTRAINT ingestion_runs_target_nonnegative CHECK (target_review_count IS NULL OR target_review_count >= 0),
    CONSTRAINT ingestion_runs_collected_nonnegative CHECK (reviews_collected >= 0)
);

CREATE INDEX ix_ingestion_runs_started_at ON ingestion_runs (started_at);
CREATE INDEX ix_ingestion_runs_status ON ingestion_runs (status);

CREATE TABLE run_targets (
    run_target_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES ingestion_runs (run_id) ON DELETE CASCADE,
    app_storefront_id uuid NOT NULL REFERENCES app_storefronts (app_storefront_id) ON DELETE RESTRICT,
    target_review_count integer,
    max_pages integer,
    reviews_collected integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending',
    stop_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_run_targets_run_app_storefront UNIQUE (run_id, app_storefront_id),
    CONSTRAINT run_targets_target_nonnegative CHECK (target_review_count IS NULL OR target_review_count >= 0),
    CONSTRAINT run_targets_max_pages_positive CHECK (max_pages IS NULL OR max_pages > 0),
    CONSTRAINT run_targets_collected_nonnegative CHECK (reviews_collected >= 0),
    CONSTRAINT run_targets_status_valid CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed', 'skipped'))
);

CREATE INDEX ix_run_targets_app_storefront_id ON run_targets (app_storefront_id);
CREATE INDEX ix_run_targets_status ON run_targets (status);

CREATE TABLE collection_requests (
    request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_target_id uuid NOT NULL REFERENCES run_targets (run_target_id) ON DELETE CASCADE,
    request_sequence integer NOT NULL,
    page_number integer,
    batch_number integer,
    cursor_in text,
    cursor_out text,
    request_url text NOT NULL,
    request_method text NOT NULL DEFAULT 'GET',
    requested_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    elapsed_seconds numeric(12, 6),
    http_status_code integer,
    success boolean NOT NULL,
    blocked boolean NOT NULL DEFAULT false,
    content_type text,
    response_size_bytes integer,
    error_type text,
    error_message text,
    status_category text NOT NULL,
    raw_review_count integer NOT NULL DEFAULT 0,
    distinct_review_count integer NOT NULL DEFAULT 0,
    distinct_from_previous_page boolean,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT collection_requests_sequence_positive CHECK (request_sequence > 0),
    CONSTRAINT collection_requests_page_positive CHECK (page_number IS NULL OR page_number > 0),
    CONSTRAINT collection_requests_batch_positive CHECK (batch_number IS NULL OR batch_number > 0),
    CONSTRAINT collection_requests_elapsed_nonnegative CHECK (elapsed_seconds IS NULL OR elapsed_seconds >= 0),
    CONSTRAINT collection_requests_status_code_valid CHECK (http_status_code IS NULL OR http_status_code BETWEEN 100 AND 599),
    CONSTRAINT collection_requests_response_size_nonnegative CHECK (response_size_bytes IS NULL OR response_size_bytes >= 0),
    CONSTRAINT collection_requests_raw_count_nonnegative CHECK (raw_review_count >= 0),
    CONSTRAINT collection_requests_distinct_count_nonnegative CHECK (distinct_review_count >= 0),
    CONSTRAINT collection_requests_distinct_lte_raw CHECK (distinct_review_count <= raw_review_count),
    CONSTRAINT collection_requests_completed_order CHECK (completed_at IS NULL OR completed_at >= requested_at),
    CONSTRAINT collection_requests_outcome_consistent CHECK (
        (success AND status_category IN ('ok', 'empty_page')) OR
        (NOT success AND status_category NOT IN ('ok', 'empty_page'))
    ),
    CONSTRAINT collection_requests_status_category_valid CHECK (
        status_category IN (
            'ok',
            'empty_page',
            'request_failed',
            'pagination_limit_or_unavailable_page',
            'json_parse_error',
            'target_limit_not_reached',
            'wrapper_evidence_incomplete',
            'skipped'
        )
    )
);

CREATE UNIQUE INDEX uq_collection_requests_run_target_sequence
    ON collection_requests (run_target_id, request_sequence);
CREATE INDEX ix_collection_requests_target_page ON collection_requests (run_target_id, page_number);
CREATE INDEX ix_collection_requests_http_status ON collection_requests (http_status_code);
CREATE INDEX ix_collection_requests_status_category ON collection_requests (status_category);
CREATE INDEX ix_collection_requests_requested_at ON collection_requests (requested_at);

CREATE TABLE raw_payloads (
    payload_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL REFERENCES collection_requests (request_id) ON DELETE CASCADE,
    storage_path text,
    payload_sha256 text NOT NULL,
    payload_json jsonb,
    captured_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT raw_payloads_sha256_shape CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT raw_payloads_storage_or_json CHECK (storage_path IS NOT NULL OR payload_json IS NOT NULL),
    CONSTRAINT uq_raw_payloads_request UNIQUE (request_id)
);

CREATE INDEX ix_raw_payloads_payload_sha256 ON raw_payloads (payload_sha256);
CREATE INDEX ix_raw_payloads_request_id ON raw_payloads (request_id);

CREATE TABLE raw_review_records (
    raw_record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload_id uuid NOT NULL REFERENCES raw_payloads (payload_id) ON DELETE CASCADE,
    source_review_id text,
    record_ordinal integer NOT NULL,
    raw_record_json jsonb NOT NULL,
    raw_record_sha256 text NOT NULL,
    parse_status text NOT NULL,
    parse_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT raw_review_records_ordinal_nonnegative CHECK (record_ordinal >= 0),
    CONSTRAINT raw_review_records_sha256_shape CHECK (raw_record_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT raw_review_records_parse_status_valid CHECK (parse_status IN ('parsed', 'excluded', 'parse_error', 'non_review_entry')),
    CONSTRAINT raw_review_records_parse_error_consistent CHECK (
        (parse_status = 'parse_error' AND parse_error IS NOT NULL) OR
        (parse_status <> 'parse_error')
    ),
    CONSTRAINT uq_raw_review_records_payload_ordinal UNIQUE (payload_id, record_ordinal)
);

CREATE INDEX ix_raw_review_records_source_review_id ON raw_review_records (source_review_id);
CREATE INDEX ix_raw_review_records_parse_status ON raw_review_records (parse_status);
CREATE INDEX ix_raw_review_records_payload_id ON raw_review_records (payload_id);

CREATE TABLE normalized_reviews (
    normalized_review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_record_id uuid NOT NULL REFERENCES raw_review_records (raw_record_id) ON DELETE CASCADE,
    source_review_id text,
    review_title text,
    review_text text,
    rating numeric(3, 1),
    review_date timestamptz,
    author_id text,
    author_name text,
    helpful_votes integer,
    app_version text,
    developer_response text,
    developer_response_date timestamptz,
    source_url text,
    raw_page_number integer,
    raw_cursor text,
    collected_at timestamptz NOT NULL,
    normalized_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    normalized_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT normalized_reviews_rating_range CHECK (rating IS NULL OR rating BETWEEN 0 AND 5),
    CONSTRAINT normalized_reviews_helpful_votes_nonnegative CHECK (helpful_votes IS NULL OR helpful_votes >= 0),
    CONSTRAINT normalized_reviews_raw_page_positive CHECK (raw_page_number IS NULL OR raw_page_number > 0),
    CONSTRAINT normalized_reviews_hash_shape CHECK (normalized_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_normalized_reviews_raw_record UNIQUE (raw_record_id)
);

CREATE INDEX ix_normalized_reviews_review_date ON normalized_reviews (review_date);
CREATE INDEX ix_normalized_reviews_source_review_id ON normalized_reviews (source_review_id);
CREATE INDEX ix_normalized_reviews_normalized_hash ON normalized_reviews (normalized_hash);

CREATE TABLE review_identities (
    review_identity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    app_storefront_id uuid NOT NULL REFERENCES app_storefronts (app_storefront_id) ON DELETE RESTRICT,
    source_review_id text NOT NULL,
    first_seen_at timestamptz NOT NULL,
    latest_seen_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT review_identities_source_review_id_nonempty CHECK (length(trim(source_review_id)) > 0),
    CONSTRAINT review_identities_seen_order CHECK (latest_seen_at >= first_seen_at),
    CONSTRAINT uq_review_identities_context_review UNIQUE (app_storefront_id, source_review_id)
);

CREATE INDEX ix_review_identities_latest_seen_at ON review_identities (latest_seen_at);

CREATE TABLE review_observations (
    observation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_identity_id uuid REFERENCES review_identities (review_identity_id) ON DELETE CASCADE,
    raw_record_id uuid NOT NULL UNIQUE REFERENCES raw_review_records (raw_record_id) ON DELETE CASCADE,
    normalized_review_id uuid REFERENCES normalized_reviews (normalized_review_id) ON DELETE SET NULL,
    observation_status text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT review_observations_status_valid CHECK (
        observation_status IN ('new', 'repeat_seen', 'duplicate_skipped', 'excluded', 'parse_error', 'non_review_entry')
    ),
    CONSTRAINT review_observations_identity_required CHECK (
        observation_status IN ('excluded', 'parse_error', 'non_review_entry') OR review_identity_id IS NOT NULL
    ),
    CONSTRAINT review_observations_normalized_consistent CHECK (
        (observation_status = 'new' AND normalized_review_id IS NOT NULL) OR
        (observation_status <> 'new' AND normalized_review_id IS NULL)
    ),
    CONSTRAINT uq_review_observations_normalized UNIQUE (normalized_review_id)
);

CREATE INDEX ix_review_observations_status ON review_observations (observation_status);
CREATE INDEX ix_review_observations_identity_id ON review_observations (review_identity_id);

CREATE TABLE quality_flags (
    quality_flag_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_review_id uuid REFERENCES normalized_reviews (normalized_review_id) ON DELETE CASCADE,
    raw_record_id uuid REFERENCES raw_review_records (raw_record_id) ON DELETE CASCADE,
    request_id uuid REFERENCES collection_requests (request_id) ON DELETE CASCADE,
    flag_type text NOT NULL,
    severity text NOT NULL,
    flag_value jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT quality_flags_severity_valid CHECK (severity IN ('info', 'warning', 'error')),
    CONSTRAINT quality_flags_one_subject CHECK (
        num_nonnulls(normalized_review_id, raw_record_id, request_id) = 1
    )
);

CREATE INDEX ix_quality_flags_type_severity ON quality_flags (flag_type, severity);
CREATE INDEX ix_quality_flags_normalized_review_id ON quality_flags (normalized_review_id);
CREATE INDEX ix_quality_flags_raw_record_id ON quality_flags (raw_record_id);
CREATE INDEX ix_quality_flags_request_id ON quality_flags (request_id);

CREATE TABLE missing_or_excluded_records (
    missing_record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_target_id uuid NOT NULL REFERENCES run_targets (run_target_id) ON DELETE CASCADE,
    request_id uuid REFERENCES collection_requests (request_id) ON DELETE SET NULL,
    reason_code text NOT NULL,
    reason_detail text,
    expected_count integer,
    observed_count integer,
    source_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT missing_records_expected_nonnegative CHECK (expected_count IS NULL OR expected_count >= 0),
    CONSTRAINT missing_records_observed_nonnegative CHECK (observed_count IS NULL OR observed_count >= 0),
    CONSTRAINT missing_records_counts_valid CHECK (
        expected_count IS NULL OR observed_count IS NULL OR observed_count <= expected_count
    ),
    CONSTRAINT missing_records_reason_nonempty CHECK (length(trim(reason_code)) > 0)
);

CREATE FUNCTION enforce_review_lineage_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    raw_context uuid;
    identity_context uuid;
    normalized_raw uuid;
BEGIN
    SELECT rt.app_storefront_id INTO raw_context
    FROM raw_review_records rrr
    JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
    JOIN collection_requests cr ON cr.request_id = rp.request_id
    JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
    WHERE rrr.raw_record_id = NEW.raw_record_id;

    IF NEW.review_identity_id IS NOT NULL THEN
        SELECT app_storefront_id INTO identity_context
        FROM review_identities WHERE review_identity_id = NEW.review_identity_id;
        IF identity_context IS DISTINCT FROM raw_context THEN
            RAISE EXCEPTION 'review identity context does not match raw record context';
        END IF;
    END IF;

    IF NEW.normalized_review_id IS NOT NULL THEN
        SELECT raw_record_id INTO normalized_raw
        FROM normalized_reviews WHERE normalized_review_id = NEW.normalized_review_id;
        IF normalized_raw IS DISTINCT FROM NEW.raw_record_id THEN
            RAISE EXCEPTION 'normalized review does not match observation raw record';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_review_lineage_consistency
BEFORE INSERT OR UPDATE ON review_observations
FOR EACH ROW EXECUTE FUNCTION enforce_review_lineage_consistency();

CREATE FUNCTION enforce_missing_request_context() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE request_target uuid;
BEGIN
    IF NEW.request_id IS NOT NULL THEN
        SELECT run_target_id INTO request_target FROM collection_requests WHERE request_id = NEW.request_id;
        IF request_target IS DISTINCT FROM NEW.run_target_id THEN
            RAISE EXCEPTION 'missing/excluded request does not match run target';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_missing_request_context
BEFORE INSERT OR UPDATE ON missing_or_excluded_records
FOR EACH ROW EXECUTE FUNCTION enforce_missing_request_context();

CREATE INDEX ix_missing_records_reason_code ON missing_or_excluded_records (reason_code);
CREATE INDEX ix_missing_records_run_target_id ON missing_or_excluded_records (run_target_id);
CREATE INDEX ix_missing_records_request_id ON missing_or_excluded_records (request_id);
