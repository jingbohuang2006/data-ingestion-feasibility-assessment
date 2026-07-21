# Apple App Store Validation EDA

## Scope
This is a larger validation path for Apple App Store review collection and EDA. It is not production-ready.

## Output Isolation
- Processed output directory: data/processed/apple_app_store_validation/apple-large-10000
- Report output directory: reports/apple_app_store_validation/apple-large-10000
- Raw output directory: data/raw/apple_app_store_validation/apple-large-10000

## Target Status
- Target review count: 10000
- Reviews collected: 6396
- Target reached: no
- Shortfall reason: Target not reached: collected 6396 of 10000 reviews because Apple RSS page depth was limited by app/storefront. Several targets returned empty pages before page 10, several high-volume targets returned unavailable-page responses around page 11, and duplicate review IDs were skipped rather than counted in the final dataset.

## Review Volume By App
- Airbnb (us/en): 300 rows, 300 unique
- Amazon Shopping (us/en): 150 rows, 150 unique
- Canva (gb/en): 50 rows, 50 unique
- Discord (us/en): 50 rows, 50 unique
- Duolingo (us/en): 250 rows, 250 unique
- Gmail (us/en): 500 rows, 500 unique
- Google Maps (us/en): 150 rows, 150 unique
- Headspace (us/en): 500 rows, 500 unique
- Instagram (us/en): 434 rows, 434 unique
- LinkedIn (us/en): 500 rows, 500 unique
- Microsoft Teams (us/en): 500 rows, 500 unique
- Netflix (us/en): 400 rows, 400 unique
- Pinterest (us/en): 500 rows, 500 unique
- Reddit (us/en): 398 rows, 398 unique
- Spotify (us/en): 400 rows, 400 unique
- TikTok (us/en): 464 rows, 464 unique
- Uber (us/en): 50 rows, 50 unique
- WhatsApp (us/en): 250 rows, 250 unique
- YouTube (us/en): 50 rows, 50 unique
- Zoom (us/en): 500 rows, 500 unique

## Limitations
- Apple review RSS access remains publicly accessible but undocumented.
- This validation does not bypass authentication, CAPTCHA, rate limits, or access controls.
- A successful validation run does not prove long-term endpoint stability or production readiness.
- Google Play remains a secondary benchmark and is not expanded in this validation path.
