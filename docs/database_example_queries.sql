-- Example analytical SQL queries for the proposed review-ingestion schema.
-- These queries assume the schema in db/schema.sql has been applied.

-- 1. Failed requests with app/storefront context.
SELECT
    r.external_run_name,
    a.canonical_name AS app_name,
    s.country_code,
    s.language_code,
    cr.page_number,
    cr.batch_number,
    cr.http_status_code,
    cr.error_type,
    cr.error_message,
    cr.requested_at
FROM collection_requests cr
JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
JOIN ingestion_runs r ON r.run_id = rt.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = rt.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
WHERE cr.status_category = 'request_failed'
   OR cr.success = false
ORDER BY cr.requested_at DESC;

-- 2. Empty pages that returned no review entries.
SELECT
    r.external_run_name,
    a.canonical_name AS app_name,
    s.country_code,
    s.language_code,
    cr.page_number,
    cr.http_status_code,
    cr.raw_review_count,
    cr.distinct_review_count
FROM collection_requests cr
JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
JOIN ingestion_runs r ON r.run_id = rt.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = rt.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
WHERE cr.status_category = 'empty_page'
ORDER BY r.started_at DESC, a.canonical_name, cr.page_number;

-- 3. Unavailable pages or pagination limits.
SELECT
    r.external_run_name,
    a.canonical_name AS app_name,
    sa.source_app_identifier,
    s.country_code,
    s.language_code,
    cr.page_number,
    cr.http_status_code,
    cr.status_category,
    cr.error_message
FROM collection_requests cr
JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
JOIN ingestion_runs r ON r.run_id = rt.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = rt.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
WHERE cr.status_category = 'pagination_limit_or_unavailable_page'
ORDER BY r.started_at DESC, a.canonical_name, cr.page_number;

-- 4. App/storefront-level shortfalls.
SELECT
    r.external_run_name,
    a.canonical_name AS app_name,
    sa.source_app_identifier,
    s.country_code,
    s.language_code,
    rt.target_review_count,
    rt.reviews_collected,
    rt.max_pages,
    rt.status,
    rt.stop_reason,
    (rt.target_review_count - rt.reviews_collected) AS shortfall_count
FROM run_targets rt
JOIN ingestion_runs r ON r.run_id = rt.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = rt.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
WHERE rt.target_review_count IS NOT NULL
  AND rt.reviews_collected < rt.target_review_count
ORDER BY shortfall_count DESC NULLS LAST;

-- 5. Duplicate and repeated review observations.
SELECT
    rs.source_code,
    a.canonical_name AS app_name,
    s.country_code,
    s.language_code,
    ri.source_review_id,
    count(*) AS observation_count,
    count(DISTINCT rt.run_id) AS run_count,
    array_agg(DISTINCT ro.observation_status ORDER BY ro.observation_status) AS statuses,
    min(ro.observed_at) AS first_observed_at,
    max(ro.observed_at) AS latest_observed_at
FROM review_observations ro
JOIN review_identities ri ON ri.review_identity_id = ro.review_identity_id
JOIN raw_review_records rrr ON rrr.raw_record_id = ro.raw_record_id
JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
JOIN collection_requests cr ON cr.request_id = rp.request_id
JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
JOIN app_storefronts ast ON ast.app_storefront_id = ri.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN review_sources rs ON rs.source_id = sa.source_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
GROUP BY rs.source_code, a.canonical_name, s.country_code, s.language_code, ri.source_review_id
HAVING count(*) > 1
ORDER BY observation_count DESC, latest_observed_at DESC;

-- 6. Missing or excluded records.
SELECT
    r.external_run_name,
    a.canonical_name AS app_name,
    s.country_code,
    s.language_code,
    mer.reason_code,
    mer.reason_detail,
    mer.expected_count,
    mer.observed_count,
    cr.page_number,
    cr.status_category,
    mer.created_at
FROM missing_or_excluded_records mer
JOIN run_targets rt ON rt.run_target_id = mer.run_target_id
JOIN ingestion_runs r ON r.run_id = rt.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = rt.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
LEFT JOIN collection_requests cr ON cr.request_id = mer.request_id
ORDER BY mer.created_at DESC;

-- 7. Raw-to-normalized traceability for one source review ID.
SELECT
    r.external_run_name,
    rs.source_code,
    a.canonical_name AS app_name,
    s.country_code,
    s.language_code,
    cr.page_number,
    cr.request_url,
    cr.http_status_code,
    rp.storage_path,
    rp.payload_sha256,
    rrr.record_ordinal,
    rrr.raw_record_sha256,
    nr.normalized_review_id,
    nr.source_review_id,
    nr.rating,
    nr.review_date,
    nr.normalized_hash
FROM normalized_reviews nr
JOIN raw_review_records rrr ON rrr.raw_record_id = nr.raw_record_id
JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
JOIN collection_requests cr ON cr.request_id = rp.request_id
JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
JOIN ingestion_runs r ON r.run_id = rt.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = rt.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN review_sources rs ON rs.source_id = sa.source_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
WHERE nr.source_review_id = :source_review_id
ORDER BY r.started_at DESC;

-- 8. Layer counts per run for operational reconciliation.
SELECT r.external_run_name,
       count(DISTINCT rt.run_target_id) AS targets,
       count(DISTINCT cr.request_id) AS requests,
       count(DISTINCT rp.payload_id) AS payloads,
       count(DISTINCT rrr.raw_record_id) AS raw_records,
       count(DISTINCT nr.normalized_review_id) AS normalized_reviews,
       count(DISTINCT ro.observation_id) AS observations
FROM ingestion_runs r
LEFT JOIN run_targets rt ON rt.run_id = r.run_id
LEFT JOIN collection_requests cr ON cr.run_target_id = rt.run_target_id
LEFT JOIN raw_payloads rp ON rp.request_id = cr.request_id
LEFT JOIN raw_review_records rrr ON rrr.payload_id = rp.payload_id
LEFT JOIN normalized_reviews nr ON nr.raw_record_id = rrr.raw_record_id
LEFT JOIN review_observations ro ON ro.raw_record_id = rrr.raw_record_id
GROUP BY r.run_id, r.external_run_name;

-- 9. Orphaned raw records or context mismatches. Expected result: zero rows.
SELECT rrr.raw_record_id
FROM raw_review_records rrr
LEFT JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
LEFT JOIN collection_requests cr ON cr.request_id = rp.request_id
LEFT JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
WHERE rp.payload_id IS NULL OR cr.request_id IS NULL OR rt.run_target_id IS NULL;

-- 10. Parsed raw records lacking a normalized or duplicate disposition. Expected: zero rows.
SELECT rrr.raw_record_id, rrr.source_review_id, rrr.parse_status
FROM raw_review_records rrr
LEFT JOIN review_observations ro ON ro.raw_record_id = rrr.raw_record_id
WHERE ro.observation_id IS NULL
   OR (rrr.parse_status = 'parsed' AND ro.observation_status NOT IN ('new', 'repeat_seen', 'duplicate_skipped'));

-- 11. Normalized rows without exactly one matching observation. Expected: zero rows.
SELECT nr.normalized_review_id, count(ro.observation_id) AS observation_count
FROM normalized_reviews nr
LEFT JOIN review_observations ro ON ro.normalized_review_id = nr.normalized_review_id
GROUP BY nr.normalized_review_id
HAVING count(ro.observation_id) <> 1;

-- 12. Duplicate identity or lineage conflicts. Expected: zero rows.
SELECT ro.observation_id
FROM review_observations ro
JOIN raw_review_records rrr ON rrr.raw_record_id = ro.raw_record_id
JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
JOIN collection_requests cr ON cr.request_id = rp.request_id
JOIN run_targets rt ON rt.run_target_id = cr.run_target_id
LEFT JOIN review_identities ri ON ri.review_identity_id = ro.review_identity_id
WHERE ri.review_identity_id IS NOT NULL
  AND (ri.app_storefront_id <> rt.app_storefront_id OR ri.source_review_id <> rrr.source_review_id);

-- 13. Quality flags with an invalid number of subjects. Expected: zero rows.
SELECT quality_flag_id
FROM quality_flags
WHERE num_nonnulls(normalized_review_id, raw_record_id, request_id) <> 1;
