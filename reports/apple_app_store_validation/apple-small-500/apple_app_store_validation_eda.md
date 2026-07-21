# Apple App Store Validation EDA

## Scope
This is a larger validation path for Apple App Store review collection and EDA. It is not production-ready.

## Output Isolation
- Processed output directory: data/processed/apple_app_store_validation/apple-small-500
- Report output directory: reports/apple_app_store_validation/apple-small-500
- Raw output directory: data/raw/apple_app_store_validation/apple-small-500

## Review Volume By App
- Duolingo (us/en): 100 rows, 100 unique
- Spotify (us/en): 250 rows, 250 unique
- YouTube (us/en): 150 rows, 150 unique

## Limitations
- Apple review RSS access remains publicly accessible but undocumented.
- This validation does not bypass authentication, CAPTCHA, rate limits, or access controls.
- A successful validation run does not prove long-term endpoint stability or production readiness.
- Google Play remains a secondary benchmark and is not expanded in this validation path.
