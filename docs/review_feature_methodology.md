# Review Feature Engineering Methodology

## Purpose and deterministic contract

This layer converts a normalized review CSV into a separate analysis-ready feature dataset. It does not
collect reviews, change normalized records, delete records, train a model, or predict sentiment. The input
path, rules path, output root, and run ID are explicit command-line arguments. Given identical input bytes,
configuration, and code, feature values and row ordering are identical.

Every input row produces exactly one output row in the same order. All normalized fields are copied before
features are calculated. Feature and report writers refuse to reuse an existing run directory, preventing
accidental overwrite. Output columns follow `FEATURE_COLUMNS` in `src/review_features.py`: the normalized
schema order followed by the documented derived-feature order.

## Versioned rules

`config/review_feature_rules_v1.yaml` is the authoritative ruleset. It records version `1.0.0`, the fixed
reference timestamp, normalization and token rules, low-signal thresholds, repeated-text behavior,
missing-field scope, language/script settings, and all issue keywords. The loader rejects missing sections,
invalid timestamps, unsupported normalization or fingerprint algorithms, invalid regular expressions, and
missing keyword categories with actionable errors.

## Text normalization and counting

Original `review_title` and `review_text` values are never rewritten. Derived calculations normalize a
working copy with Unicode NFKC normalization, Unicode case folding, whitespace collapsing, and trimming.
Null, empty, and whitespace-only values normalize to the empty string and are consistently absent.

Character counts use the length of that normalized working copy. Word counts use the configured
Unicode-aware regular expression. A word is a sequence of Unicode alphanumeric letters/characters excluding
underscore, optionally containing an internal ASCII or curly apostrophe.

## Low-signal text

`low_signal_text` is true when review text is absent, has fewer than 15 normalized characters, or has fewer
than 3 words. It is a text-signal indicator, not a deletion rule. The row remains in the feature dataset.

## Repeated text

The fingerprint input is normalized title, a newline separator, and normalized review text. Non-empty values
are hashed with SHA-256. Repetition is grouped within:

`source + app_identifier + country + language + fingerprint`

`app_identifier` deterministically selects the first available value from `item_id`, `package_id`,
`item_name`, and `app_name`, retaining the field name in the scoped value. Every member of a group larger
than one is flagged. Empty title-and-text records are not grouped as repeated. Rows are never removed.
The SHA-256 fingerprint is review-safe derived text metadata rather than readable review content.

## Language indicator

`declared_language_available` only reports whether the normalized source supplied a language. The lightweight
`language_script_consistent` indicator does not claim language detection. For configured English records with
at least three alphabetic characters, it checks whether at least 70% of letters have Unicode Latin script
names. Unsupported languages and too-short text yield null. Mixed-script or transliterated text can be
misclassified; future production language detection should be separately evaluated and versioned.

## Timestamps and review age

Publication timestamps must be timezone-aware ISO-8601 strings. Valid values are converted to UTC for
calculation. Missing, malformed, or timezone-naive values produce null year, month, day-of-week, and age,
with `publication_timestamp_missing_or_invalid=true`. The distinct
`missing_publication_timestamp` flag is true only when the source value is absent.

`review_age_days` is the exact fractional number of 24-hour days from publication to the fixed
`2026-07-07T00:00:00Z` reference. It never uses the system clock. Negative values are retained when a review
is later than the reference timestamp because altering them would conceal source/reference inconsistencies.

## Metadata and quality treatment

App version and developer reply are availability indicators. In particular, `has_developer_reply=false`
does not set `low_signal_text` or any general quality-failure field. Missing title, text, rating, and
publication timestamp are independent flags. Invalid non-empty timestamps are additionally identified by the
parse-validity flag.

## Keyword issue signals

Each issue category is matched independently against normalized title plus normalized review text. Keywords
and phrases come only from the versioned YAML. Matching uses Unicode word boundaries implemented as
non-word lookarounds; spaces inside phrases accept normalized whitespace. A review can activate multiple
categories. Multiple matches in one category still produce one Boolean value. Substrings inside larger words
do not match.

These signals are transparent lexical indicators, not sentiment predictions.

## Lineage and future PostgreSQL integration

Every normalized field remains in the output, including review ID, source/app/storefront context, source URL,
collection timestamp, raw page number, and raw cursor. A future PostgreSQL adapter should query normalized
rows into this same column contract, call the pure feature generator, and insert results into a separate,
versioned feature table keyed to the normalized review identity and feature-rule version. It must not update
raw or normalized tables.

## Target-leakage warning

No rating-derived sentiment label is created here. If a future project derives sentiment targets from rating,
then rating and every rating-derived field must be excluded from model inputs. Using them would disclose the
target definition to the model and create target leakage.
