# Review Feature Validation Report

This deterministic report uses observed rows; run names are not interpreted as row counts.

## Row and lineage validation

- Input rows: 6396
- Output rows: 6396
- Row count preserved: True
- Unique contextual review identities: 6396
- Duplicate contextual identities: 0
- Required lineage fields retained: True

## Overall feature rates

| Feature | Rate |
|---|---:|
| `missing_title` | 0.0000% |
| `missing_review_text` | 0.0000% |
| `missing_rating` | 0.0000% |
| `missing_publication_timestamp` | 0.0000% |
| `publication_timestamp_missing_or_invalid` | 0.0000% |
| `has_developer_reply` | 0.0000% |
| `has_app_version` | 100.0000% |
| `low_signal_text` | 8.6148% |
| `repeated_text` | 0.1407% |
| `issue_login` | 3.0175% |
| `issue_payment` | 4.3777% |
| `issue_performance` | 2.4859% |
| `issue_subscription` | 1.8762% |
| `issue_delivery` | 0.5629% |
| `issue_customer_service` | 2.6892% |

Developer-reply absence is metadata availability only and is not an automatic quality failure.

## App and storefront coverage

| App | Country | Language | Rows |
|---|---|---|---:|
| Airbnb | us | en | 300 |
| Amazon Shopping | us | en | 150 |
| Canva | gb | en | 50 |
| Discord | us | en | 50 |
| Duolingo | us | en | 250 |
| Gmail | us | en | 500 |
| Google Maps | us | en | 150 |
| Headspace | us | en | 500 |
| Instagram | us | en | 434 |
| LinkedIn | us | en | 500 |
| Microsoft Teams | us | en | 500 |
| Netflix | us | en | 400 |
| Pinterest | us | en | 500 |
| Reddit | us | en | 398 |
| Spotify | us | en | 400 |
| TikTok | us | en | 464 |
| Uber | us | en | 50 |
| WhatsApp | us | en | 250 |
| YouTube | us | en | 50 |
| Zoom | us | en | 500 |

Detailed text, rating, timestamp, missingness, metadata, signal, and keyword distributions are in `feature_distributions.csv`.
