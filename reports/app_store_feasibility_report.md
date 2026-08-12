# Phase 2 App Store Feasibility Report

## Executive Summary
Apple App Store is the stronger primary app-store source under the current evidence because its public RSS review feed was more accessible and maintainable in this environment. This is not a risk-free production API: the feed is publicly accessible but undocumented, is not an official supported Apple review API, and long-term endpoint and schema stability are not guaranteed. The two immediate successful runs do not prove long-term repeatability, and the observed 100% cross-run overlap may only reflect an unchanged recent-review window during closely timed runs. Incremental ingestion is conditionally feasible only while stable review IDs and stable ordering remain available. Google Play Store should be used as a secondary source only after the unofficial third-party access path is approved for use and monitored, even though it worked repeatably in this limited run. Before production use, the selected approach needs monitoring, failure detection, schema-change alerts, explicit rate limits, stakeholder/legal approval, and approved access review. Steam is no longer recommended as the main source because stakeholder concerns about gaming-specific commercial relevance supersede the earlier technical recommendation; Amazon remains on hold because repeatable programmatic access was not resolved in this phase.

## Scope and Methodology
This phase assesses Google Play Store and Apple App Store reviews as potential primary sources for future review ingestion and product-intelligence work. It uses modest request limits, conservative pacing, and no authentication or access-control bypass.

## Test App and Identifiers
- App name: YouTube
- Google Play package ID: com.google.android.youtube
- Apple App Store app ID: 544007664
- Storefront/country: us
- Language: en
- Selection reason: widely available, high-volume app present on both platforms.

## Google Play Store Findings
- Live request executed: yes
- Live collection executed: yes
- Offline saved-response parsing executed: no
- Saved response batches parsed: 0
- Live requests attempted: unavailable via third-party wrapper
- Successful requests: unavailable via third-party wrapper
- Request count status: unavailable_via_third_party_wrapper
- HTTP status codes: none
- Reviews collected: 100
- Final dataset duplicate count: 0
- Cross-run overlap count: 100
- Cross-run overlap rate: 100%
- New records in second run: 0
- Blocking status: no
- CAPTCHA status: no
- Pagination demonstrated: yes
- Parser errors: 0
- Warnings: none
- Access method: google-play-scraper reviews API wrapper
- Access method classification: third-party unofficial library
- Country/storefront: us
- Language: en
- Run timestamps: 2026-07-03T12:35:54.205213+00:00, 2026-07-03T12:35:56.143487+00:00
- Batches/pages attempted: 4
- Batches/pages completed: 4
- Repeated collection demonstrated: yes
- Incremental collection appears feasible: yes
- Access limitations observed: Access depends on an unofficial third-party library and undocumented Google Play behavior.

## Apple App Store Findings
- Live request executed: yes
- Live collection executed: yes
- Offline saved-response parsing executed: no
- Saved response batches parsed: 0
- Live requests attempted: 4
- Successful requests: 4
- Request count status: available
- HTTP status codes: 200, 200, 200, 200
- Reviews collected: 100
- Final dataset duplicate count: 0
- Cross-run overlap count: 100
- Cross-run overlap rate: 100%
- New records in second run: 0
- Blocking status: no
- CAPTCHA status: no
- Pagination demonstrated: yes
- Parser errors: 0
- Warnings: none
- Access method: Apple customer reviews RSS JSON feed
- Access method classification: publicly accessible undocumented feed
- Country/storefront: us
- Language: en
- Run timestamps: 2026-07-03T12:35:58.177003+00:00, 2026-07-03T12:36:00.058227+00:00
- Batches/pages attempted: 4
- Batches/pages completed: 4
- Repeated collection demonstrated: yes
- Incremental collection appears feasible: yes
- Access limitations observed: none

## Accessibility and Access-Method Comparison
- Google Play evidence: method=google-play-scraper reviews API wrapper; method_type=third-party unofficial library; request_count=unavailable; success_rate=unavailable; request_count_status=unavailable_via_third_party_wrapper; live_collection=True; errors=0
- Apple App Store evidence: method=Apple customer reviews RSS JSON feed; method_type=publicly accessible undocumented feed; request_count=4; success_rate=1.0; request_count_status=available; live_collection=True; errors=0
- Google Play assessment: Technically feasible in this run, but access depends on an unofficial library.
- Apple App Store assessment: Strong in this limited live test.
- Confidence: limited

## Pagination/Batching Comparison
- Google Play evidence: attempted=4; completed=4; pagination_demonstrated=True; batches=4
- Apple App Store evidence: attempted=4; completed=4; pagination_demonstrated=True; batches=4
- Google Play assessment: Demonstrated.
- Apple App Store assessment: Demonstrated.
- Confidence: limited

## Metadata Field Comparison
- source: Google Play=available; Apple App Store=available
- app_name: Google Play=available; Apple App Store=available
- item_id: Google Play=available; Apple App Store=available
- package_id: Google Play=available; Apple App Store=unavailable
- review_id: Google Play=available; Apple App Store=available
- review_title: Google Play=unavailable; Apple App Store=available
- review_text: Google Play=available; Apple App Store=available
- rating: Google Play=available; Apple App Store=available
- review_date: Google Play=available; Apple App Store=available
- author_name: Google Play=available; Apple App Store=available
- author_id: Google Play=unavailable; Apple App Store=unavailable
- helpful_votes: Google Play=available; Apple App Store=available
- app_version: Google Play=available; Apple App Store=available
- language: Google Play=available; Apple App Store=available
- country: Google Play=available; Apple App Store=available
- developer_response: Google Play=unavailable; Apple App Store=unavailable
- developer_response_date: Google Play=unavailable; Apple App Store=unavailable
- source_url: Google Play=available; Apple App Store=available
- raw_page_number: Google Play=available; Apple App Store=available
- raw_cursor: Google Play=available; Apple App Store=unavailable
- collected_at: Google Play=available; Apple App Store=available

## Data-Quality and Repeatability Results
- google_play: rows=100, unique=100, final dataset duplicate count=0, cross-run overlap count=100, cross-run overlap rate=100%, new records in second run=0, empty text=0, parser errors=0
- apple_app_store: rows=100, unique=100, final dataset duplicate count=0, cross-run overlap count=100, cross-run overlap rate=100%, new records in second run=0, empty text=0, parser errors=0

## Access Limitations and Compliance Considerations
No authentication bypass, CAPTCHA solving, stealth browser behavior, or rate-limit evasion was used. Google Play access is classified as third-party/unofficial when using google-play-scraper. Apple access is classified as a publicly accessible undocumented RSS JSON feed, not an official supported Apple review API. Production use requires monitoring, failure detection, schema-change alerts, platform-policy review, and stakeholder/legal approval.

## Long-Term Maintainability Risks
Apple's RSS JSON shape is simple, but long-term endpoint and schema stability are not guaranteed. Two immediate successful runs do not prove long-term repeatability, and the observed 100% cross-run overlap may only reflect an unchanged recent-review window during two closely timed runs. Incremental ingestion is conditionally feasible only while stable review IDs and stable ordering remain available. Google Play is riskier because the selected path depends on an unofficial package and undocumented store behavior.

## Commercial Value and Generalizability
Both app stores are better aligned than Steam with broad consumer-product feedback and app product intelligence. The earlier Steam recommendation is superseded by stakeholder concerns that Steam is too gaming-specific. Amazon remains commercially valuable but on hold until repeatable access is resolved.

## Limitations of This Assessment
- Results reflect only the configured app, country, language, network environment, and execution time.
- Apple is recommended only as the stronger source under the current tested constraints, not as a risk-free production API.
- Empty or failed live results are not treated as successful access.
- Offline fixtures validate parsers only; they are not evidence of live platform access.
- Sample sizes are capped and cannot estimate total platform review volume.

## Final Recommendation
Apple App Store is the stronger primary app-store source under the current evidence because its public RSS review feed was more accessible and maintainable in this environment. This is not a risk-free production API: the feed is publicly accessible but undocumented, is not an official supported Apple review API, and long-term endpoint and schema stability are not guaranteed. The two immediate successful runs do not prove long-term repeatability, and the observed 100% cross-run overlap may only reflect an unchanged recent-review window during closely timed runs. Incremental ingestion is conditionally feasible only while stable review IDs and stable ordering remain available. Google Play Store should be used as a secondary source only after the unofficial third-party access path is approved for use and monitored, even though it worked repeatably in this limited run. Before production use, the selected approach needs monitoring, failure detection, schema-change alerts, explicit rate limits, stakeholder/legal approval, and approved access review. Steam is no longer recommended as the main source because stakeholder concerns about gaming-specific commercial relevance supersede the earlier technical recommendation; Amazon remains on hold because repeatable programmatic access was not resolved in this phase.
