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
    count(DISTINCT ro.run_id) AS run_count,
    array_agg(DISTINCT ro.observation_status ORDER BY ro.observation_status) AS statuses,
    min(ro.observed_at) AS first_observed_at,
    max(ro.observed_at) AS latest_observed_at
FROM review_observations ro
JOIN review_identities ri ON ri.review_identity_id = ro.review_identity_id
JOIN review_sources rs ON rs.source_id = ri.source_id
JOIN app_storefronts ast ON ast.app_storefront_id = ri.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
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
JOIN collection_requests cr ON cr.request_id = rrr.request_id
LEFT JOIN raw_payloads rp ON rp.payload_id = rrr.payload_id
JOIN ingestion_runs r ON r.run_id = nr.run_id
JOIN app_storefronts ast ON ast.app_storefront_id = nr.app_storefront_id
JOIN source_apps sa ON sa.source_app_id = ast.source_app_id
JOIN review_sources rs ON rs.source_id = sa.source_id
JOIN apps a ON a.app_id = sa.app_id
JOIN storefronts s ON s.storefront_id = ast.storefront_id
WHERE nr.source_review_id = :source_review_id
ORDER BY r.started_at DESC;
