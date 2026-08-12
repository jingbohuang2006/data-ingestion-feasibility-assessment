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
| `repeated_full_content` | 0.1407% |
| `repeated_review_body` | 0.8130% |
| `login_topic_signal` | 3.0175% |
| `payment_topic_signal` | 4.3777% |
| `performance_topic_signal` | 2.4859% |
| `subscription_topic_signal` | 1.8762% |
| `delivery_topic_signal` | 0.5629% |
| `customer_service_topic_signal` | 2.6892% |

Developer-reply absence is metadata availability only and is not an automatic quality failure.

## Weak sentiment label coverage

These rating-derived counts describe sampling coverage only; they are not validated sentiment outcomes.

| Weak label | Rows |
|---|---:|
| `negative` | 3485 |
| `positive` | 2410 |
| `neutral` | 501 |

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

Detailed text, age, rating, timestamp, missingness, metadata, and topic-signal distributions are in `feature_distributions.csv`.

## Manual validation analysis

This section uses only the 135 completed rows in `manual_validation_sample_annotated.csv`. The human labels
were assigned independently from the rating-derived weak labels. For analysis, title-cased human sentiment was
matched case-insensitively, `sentiment_agreement=Yes` was interpreted as agreement, and
`mixed_or_unclear=Yes` was interpreted as mixed or unclear. The annotation source file was not rewritten.

These are validation results for weak labels and deterministic rules. They are not model-accuracy metrics.

### Weak-label agreement

Overall agreement was **105 of 135 records (77.8%)**.

| Rating-derived weak label | Annotated rows | Agreements | Disagreements | Agreement rate | Human-label outcomes |
|---|---:|---:|---:|---:|---|
| Negative | 51 | 51 | 0 | 100.0% | 51 negative |
| Neutral | 38 | 12 | 26 | 31.6% | 24 negative, 12 neutral, 2 positive |
| Positive | 46 | 42 | 4 | 91.3% | 1 negative, 3 neutral, 42 positive |
| **Overall** | **135** | **105** | **30** | **77.8%** | 76 negative, 15 neutral, 44 positive |

Agreement is strongly dependent on class. Within this sample, the negative and positive weak-label groups are
reliable enough for limited baseline dataset grouping when they remain explicitly identified as rating-derived
weak labels. The neutral group is not reliable enough: 26 of 38 three-star reviews received a different human
sentiment, most often negative.

### Mixed or unclear reviews

**47 of 135 records (34.8%)** were annotated as mixed or unclear.

| Weak-label group | Mixed/unclear | Group rows | Rate |
|---|---:|---:|---:|
| Negative | 10 | 51 | 19.6% |
| Neutral | 22 | 38 | 57.9% |
| Positive | 15 | 46 | 32.6% |
| **Overall** | **47** | **135** | **34.8%** |

The high neutral-group rate reinforces that a three-star rating is an especially weak proxy for neutral text.
Mixed or unclear wording also exists in the positive and negative groups, so downstream baseline analyses should
retain this annotation distinction rather than equating star-derived classes with unambiguous textual sentiment.

### Topic-signal relevance

Fourteen sampled records contained at least one topic signal, producing 18 signal activations. Every emitted
activation was annotated as relevant to its intended topic. This evaluates relevance (observed precision) only;
it does not measure topics missed by the keyword rules.

| Topic signal | Relevant activations | Total reviewed activations | Observed relevance | Apps represented |
|---|---:|---:|---:|---|
| Login | 3 | 3 | 100.0% | Discord, Headspace, TikTok |
| Payment | 4 | 4 | 100.0% | Airbnb (2), Amazon Shopping, Headspace |
| Performance | 2 | 2 | 100.0% | Instagram, TikTok |
| Subscription | 3 | 3 | 100.0% | Headspace (3) |
| Delivery | 1 | 1 | 100.0% | Amazon Shopping |
| Customer service | 5 | 5 | 100.0% | Airbnb, Amazon Shopping (2), Headspace, Zoom |
| **All activations** | **18** | **18** | **100.0%** | 7 distinct Apps across signal rows |

Login, payment, performance, and customer-service signals were relevant in every reviewed activation across
multiple Apps. That is encouraging evidence of cross-App consistency for the sampled uses. Subscription and
delivery cannot support a cross-App conclusion because their reviewed activations came from only one App each.
No topic-rule false positive was observed, but the small, coverage-oriented cells are not sufficient to claim a
stable population relevance rate.

### Repetition-rule evaluation

| Rule | Flagged sampled rows | Human-confirmed duplicates | Observed flagged-row confirmation |
|---|---:|---:|---:|
| `repeated_full_content` | 2 | 2 | 100.0% |
| `repeated_review_body` | 3 | 3 | 100.0% |

Both full-content flags and all three body-only flags were confirmed using the supplied same-scope peer examples.
No false positive was observed. The sample is too small to estimate a stable precision rate, and reviewing one
peer for flagged records does not test recall or discover unflagged paraphrases. The current evidence does not
indicate that either exact-repetition rule needs refinement.

## Answers to the validation questions

1. **Which sentiment groups are reliable enough for baseline dataset usage?** Negative (100.0% agreement) and
   positive (91.3%) are reliable enough for limited baseline grouping within the constraints of this sample.
   They must remain labeled as weak, rating-derived groups rather than ground truth. Neutral (31.6%) is not
   reliable enough and should be excluded from sentiment-baseline conclusions or manually reviewed.
2. **Which feature rules require refinement?** The three-star-to-neutral weak-label rule requires refinement or
   explicit exclusion. The high mixed/unclear rate, particularly 57.9% in the neutral weak-label group, should be
   carried into validation decisions. The annotated sample provides no evidence that the topic relevance or exact
   repetition rules require immediate refinement, although it cannot evaluate topic recall and contains too few
   repeated examples for a strong conclusion.
3. **Do topic signals behave consistently across different Apps?** The observed login, payment, performance, and
   customer-service activations were consistently relevant across the Apps represented. Subscription and delivery
   lack enough App diversity to answer this question. Overall, the sample shows no cross-App inconsistency, but the
   evidence is preliminary rather than conclusive.

## Manual-validation limitations

- The 135 rows were selected for coverage, not as a simple random or population-representative sample; unweighted
  rates should not be projected to all 6,396 reviews.
- The analysis reflects one completed annotation set. No independent second-reviewer agreement statistic is
  available.
- Topic-signal results cover only 18 emitted activations. They evaluate relevance of matches, not recall or missed
  vocabulary, and several App/topic cells contain only one record.
- Repetition evaluation contains only two full-content and three body-only flagged rows. It evaluates the supplied
  exact-match peer examples, not semantic similarity or recall among unflagged records.
- Mixed/unclear is a reviewer judgment and does not invalidate the assigned dominant sentiment by itself.
- Subsequent stakeholder approval permits the audited positive and negative weak-label groups as an exploratory
  rating-derived prediction target after excluding three-star reviews. `rating`, `weak_sentiment_label`, and every
  rating-derived field remain prohibited as model inputs. The target is not manually verified sentiment ground
  truth, and all 135 audited rows are reserved outside training and the main split for post-training diagnostics.
