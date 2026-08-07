# Manual Validation Annotation Guidelines

## Purpose

Use these guidelines to annotate the 135 records in
`reports/review_features/apple-large-feature-v2/manual_validation_sample.csv`. The objective is to evaluate
the quality of rating-derived weak sentiment labels, lexical topic signals, and repeated-content rules. This
is data-quality validation, not model training.

Annotate the meaning expressed by `review_title` and `review_text`. Do not infer sentiment from `rating` or
`weak_sentiment_label`; those fields are shown only so agreement can be recorded after the independent human
label is chosen. Do not research the reviewer, App, or underlying event.

## Reviewer procedure

For each row, use this order:

1. Read `review_title` and `review_text` without consulting the rating or weak label.
2. Assign `human_sentiment` and `mixed_or_unclear`.
3. Compare the human label with `weak_sentiment_label` and fill `sentiment_agreement`.
4. Evaluate every topic signal that is `True` and fill `topic_signal_relevance`.
5. If a repetition flag is `True`, compare the review with the supplied example peer and record the
   corresponding duplication judgment.
6. Set `annotation_status` to `complete` only after all applicable fields are filled.

Use lowercase values exactly as specified. Do not alter source, feature, rating, weak-label, or peer-example
columns. Save the file as UTF-8 CSV and preserve all 135 rows and their order.

## Human sentiment

Allowed `human_sentiment` values are `positive`, `neutral`, and `negative`.

### Positive

Choose `positive` when the review's dominant evaluation is favorable: praise, satisfaction, endorsement,
gratitude, enjoyment, or a recommendation. A minor reservation does not overturn a clearly positive overall
assessment.

Examples:

- “Love the app; search could be faster.” → `positive`
- “The update fixed my problem, thank you.” → `positive`

### Neutral

Choose `neutral` when the review is mainly factual, descriptive, a question/request without a clear favorable
or unfavorable evaluation, or when positive and negative evaluations are genuinely balanced.

Examples:

- “Does this support offline downloads?” → `neutral`
- “Great catalog, but frequent crashes make it hard to use.” with no dominant side → `neutral`

Do not use `neutral` merely because the rating is three stars.

### Negative

Choose `negative` when the dominant evaluation is unfavorable: dissatisfaction, criticism, frustration,
failure, cancellation intent, warning, or a request to fix a harmful problem. Brief praise does not overturn
a clearly negative overall assessment.

Examples:

- “Used to be great, but it now crashes every time.” → `negative`
- “Charged twice and support did not help.” → `negative`

### Insufficient text

If the text is empty, unintelligible, or too fragmentary to support any of the three classes, leave
`human_sentiment` blank, set `mixed_or_unclear` to `yes`, and use `not_assessable` for
`sentiment_agreement`. Do not invent a sentiment from the rating.

## Mixed or unclear

Allowed `mixed_or_unclear` values are `yes` and `no`.

Use `yes` when at least one condition applies:

- substantial positive and negative evaluations coexist;
- sarcasm, irony, ambiguous referents, or contradictory wording prevents confident interpretation;
- the text is too short, corrupted, or unintelligible;
- the text reports an event but does not make the author's attitude clear.

Use `no` when the dominant sentiment is reasonably clear, including reviews with a minor secondary caveat.
When a review is mixed but one side dominates, assign the dominant human sentiment and still mark `yes`.

## Sentiment agreement

Allowed `sentiment_agreement` values are `agree`, `disagree`, and `not_assessable`.

- `agree`: `human_sentiment` exactly equals `weak_sentiment_label`.
- `disagree`: both labels are present and differ.
- `not_assessable`: no defensible human sentiment can be assigned, or the weak label is missing.

Agreement measures the rating-derived proxy against an independently read human label. Never change the
human label to match the rating. `mixed_or_unclear=yes` does not automatically mean disagreement.

## Topic signal relevance

The six Boolean fields are lexical detections, not validated problems:

- `login_topic_signal`
- `payment_topic_signal`
- `performance_topic_signal`
- `subscription_topic_signal`
- `delivery_topic_signal`
- `customer_service_topic_signal`

For every signal that is `True`, judge whether the matched vocabulary is used in the intended topic sense.
Use a semicolon-separated `signal=value` list in `topic_signal_relevance`, in the field order above. Allowed
values are `relevant`, `irrelevant`, and `unclear`.

Examples:

- `payment=relevant;customer_service=relevant`
- `performance=irrelevant` when “performance” refers to a concert rather than App behavior
- `subscription=unclear` when fragmentary text does not reveal the intended sense

Use `none` when all six topic signals are `False`. A signal can be relevant even when the user is praising the
topic (“payment was easy”), because relevance evaluates topic meaning, not whether an issue occurred. Do not
add topics that the feature rules failed to flag; record only the relevance of emitted signals.

## Repeated-content judgments

The sample provides one same-scope peer example for each `True` repetition flag. Compare normalized meaning,
ignoring case differences, Unicode-width variants, leading/trailing whitespace, and repeated internal
whitespace—the same non-semantic differences ignored by the rule.

Allowed values for both judgment columns are `correct`, `incorrect`, `unable_to_assess`, and
`not_applicable`.

### Full content

For `full_content_duplication_judgment`, compare the current title and body with
`repeated_full_content_example_title` and `repeated_full_content_example_body`.

- `correct`: both title and body are identical after the non-semantic normalization above.
- `incorrect`: either title or body has a substantive difference.
- `unable_to_assess`: the flag is true but peer context is missing or corrupted.
- `not_applicable`: `repeated_full_content` is false.

### Review body

For `review_body_duplication_judgment`, compare only the current body with
`repeated_review_body_example_body`. Titles may differ.

- `correct`: bodies are identical after non-semantic normalization.
- `incorrect`: bodies have a substantive difference.
- `unable_to_assess`: the flag is true but peer context is missing or corrupted.
- `not_applicable`: `repeated_review_body` is false.

These judgments validate exact-duplication rule behavior. Do not mark paraphrases or merely similar reviews
as exact duplicates.

## Completion and quality control

Before delivery, verify:

- exactly 135 rows remain and every `review_id` is unchanged;
- every completed row has `human_sentiment` or the documented insufficient-text exception;
- every row has `sentiment_agreement` and `mixed_or_unclear`;
- every row has `topic_signal_relevance`, using `none` where no topic signal fired;
- both duplication judgments are completed, using `not_applicable` when the corresponding flag is false;
- `annotation_status=complete` only when all applicable judgments are present.

For reproducibility, a second reviewer should independently annotate a small overlap (recommended: 15–20
records covering all three weak labels and at least one example of each signal type). Resolve disagreements by
applying these written rules, and record any guideline change before revising earlier annotations.

## Post-annotation analysis

After annotation, report sentiment agreement separately for negative, neutral, and positive weak-label groups;
inspect mixed/unclear rates and disagreement examples; calculate topic relevance by signal and App; and review
false repetition flags. Small App/topic cells are descriptive and should not be presented as stable rates.

The resulting evidence should answer which weak-label groups are adequate for baseline dataset use, which
rules require refinement, and whether topic signals behave consistently across Apps. It does not authorize
modeling, and neither `rating` nor `weak_sentiment_label` may be used as model features or prediction targets.
