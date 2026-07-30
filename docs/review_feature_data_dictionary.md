# Review Feature Data Dictionary

All nullable source fields preserve their normalized input value. Boolean derived fields are non-null unless
explicitly stated. `string` includes ISO-8601 timestamp strings where noted.

## Preserved normalized fields

| Feature name | Type | Source | Calculation logic | Null behavior | Interpretation |
|---|---|---|---|---|---|
| `source` | string | `source` | Copied unchanged | Required by normalized schema | Review platform/source |
| `app_name` | string | `app_name` | Copied unchanged | Preserved | Human-readable app |
| `item_id` | string | `item_id` | Copied unchanged | Preserved | Source item identifier |
| `package_id` | string | `package_id` | Copied unchanged | Preserved | Package identifier |
| `item_name` | string | `item_name` | Copied unchanged | Preserved | Source item name |
| `review_id` | string | `review_id` | Copied unchanged | Preserved | Source review identifier |
| `review_title` | string | `review_title` | Copied unchanged | Preserved | Original review title |
| `review_text` | string | `review_text` | Copied unchanged | Preserved | Original review body |
| `rating` | number | `rating` | Copied unchanged | Preserved | Source rating |
| `recommendation` | boolean | `recommendation` | Copied unchanged | Preserved | Source recommendation |
| `review_date` | string | `review_date` | Copied unchanged | Preserved | Original publication timestamp |
| `author_id` | string | `author_id` | Copied unchanged | Preserved | Source author ID |
| `author_name` | string | `author_name` | Copied unchanged | Preserved | Source author name |
| `verified_purchase` | boolean | `verified_purchase` | Copied unchanged | Preserved | Verified-purchase metadata |
| `helpful_votes` | integer | `helpful_votes` | Copied unchanged | Preserved | Helpful-vote count |
| `funny_votes` | integer | `funny_votes` | Copied unchanged | Preserved | Funny-vote count |
| `playtime_forever` | integer | `playtime_forever` | Copied unchanged | Preserved | Lifetime playtime |
| `playtime_at_review` | integer | `playtime_at_review` | Copied unchanged | Preserved | Playtime at publication |
| `app_version` | string | `app_version` | Copied unchanged | Preserved | Reviewed app version |
| `language` | string | `language` | Copied unchanged | Preserved | Source-declared language |
| `country` | string | `country` | Copied unchanged | Preserved | Storefront country |
| `developer_response` | string | `developer_response` | Copied unchanged | Preserved | Original developer reply |
| `developer_response_date` | string | `developer_response_date` | Copied unchanged | Preserved | Developer-reply timestamp |
| `source_url` | string | `source_url` | Copied unchanged | Preserved | Collection/source URL |
| `collected_at` | string | `collected_at` | Copied unchanged | Preserved | Collection timestamp |
| `raw_page_number` | integer | `raw_page_number` | Copied unchanged | Preserved | Source page lineage |
| `raw_cursor` | string | `raw_cursor` | Copied unchanged | Preserved | Source cursor lineage |

## Derived features

| Feature name | Type | Source | Calculation logic | Null behavior | Interpretation |
|---|---|---|---|---|---|
| `publication_timestamp` | string | `review_date` | Alias copied unchanged | Preserved | Explicit publication timestamp |
| `review_text_character_count` | integer | `review_text` | Length after configured matching normalization | `0` when absent | Comparable review-body length |
| `review_text_word_count` | integer | `review_text` | Count configured Unicode word regex matches | `0` when absent | Review-body word count |
| `title_character_count` | integer | `review_title` | Length after configured matching normalization | `0` when absent | Comparable title length |
| `title_word_count` | integer | `review_title` | Count configured Unicode word regex matches | `0` when absent | Title word count |
| `has_review_text` | boolean | `review_text` | True after trim/normalization when non-empty | Never null | Review body availability |
| `has_title` | boolean | `review_title` | True after trim/normalization when non-empty | Never null | Title availability |
| `publication_year` | integer | `review_date` | UTC year of valid timestamp | Null when missing/invalid | Publication year |
| `publication_month` | integer | `review_date` | UTC month, 1–12 | Null when missing/invalid | Publication month |
| `publication_day_of_week` | string | `review_date` | English UTC weekday name | Null when missing/invalid | Publication weekday |
| `review_age_days` | number | `review_date`, rules | Fractional days to fixed reference timestamp | Null when missing/invalid | Reproducible review age |
| `publication_timestamp_missing_or_invalid` | boolean | `review_date` | True when absent or not timezone-aware ISO-8601 | Never null | Timestamp usability flag |
| `has_app_version` | boolean | `app_version` | Non-null/non-blank check | Never null | App-version availability |
| `has_developer_reply` | boolean | `developer_response` | Non-null/non-blank check | Never null | Reply availability, not quality |
| `low_signal_text` | boolean | `review_text`, rules | Absent or below configured character/word threshold | Never null | Weak review-body text signal |
| `repeated_text` | boolean | title, text, scope | Group size greater than one | Never null | Repeated content within scope |
| `repeated_text_fingerprint` | string | title, text | SHA-256 of normalized title/body | Null when both are empty | Stable review-safe content key |
| `repeated_text_group_size` | integer | fingerprint, scope | Size of scoped fingerprint group | `0` for empty content | Repeated group membership size |
| `missing_title` | boolean | `review_title` | Inverse of `has_title` | Never null | Missing/blank title |
| `missing_review_text` | boolean | `review_text` | Inverse of `has_review_text` | Never null | Missing/blank body |
| `missing_rating` | boolean | `rating` | Null/blank check | Never null | Rating availability |
| `missing_publication_timestamp` | boolean | `review_date` | Null/blank check only | Never null | Timestamp source availability |
| `declared_language_available` | boolean | `language` | Null/blank check | Never null | Declared-language availability |
| `language_script_consistent` | boolean | language, title, text, rules | Latin-letter ratio for supported English text | Null when unsupported/too short | Limited script consistency, not detection |
| `issue_login` | boolean | title, text, rules | Boundary match for configured login terms | Never null | Login issue vocabulary present |
| `issue_payment` | boolean | title, text, rules | Boundary match for configured payment terms | Never null | Payment issue vocabulary present |
| `issue_performance` | boolean | title, text, rules | Boundary match for configured performance terms | Never null | Performance issue vocabulary present |
| `issue_subscription` | boolean | title, text, rules | Boundary match for configured subscription terms | Never null | Subscription vocabulary present |
| `issue_delivery` | boolean | title, text, rules | Boundary match for configured delivery terms | Never null | Delivery issue vocabulary present |
| `issue_customer_service` | boolean | title, text, rules | Boundary match for configured service terms | Never null | Customer-service vocabulary present |
| `feature_rule_version` | string | rules | Copied validated rule version | Never null | Feature definition version |
| `feature_reference_timestamp` | string | rules | Canonical fixed UTC reference | Never null | Review-age calculation reference |
