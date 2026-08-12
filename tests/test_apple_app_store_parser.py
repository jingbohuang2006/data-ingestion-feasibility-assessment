from __future__ import annotations

import json
from pathlib import Path

from src.apple_app_store_probe import parse_apple_app_store_reviews


FIXTURES = Path(__file__).parent / "fixtures"


def test_apple_app_store_rss_parsing_normalizes_fields() -> None:
    payload = json.loads((FIXTURES / "apple_app_store_reviews.json").read_text(encoding="utf-8"))

    reviews = parse_apple_app_store_reviews(
        payload,
        app_id="324684580",
        app_name="Spotify",
        country="us",
        language="en",
        source_url="https://example.test/apple",
        page_number=1,
    )

    assert len(reviews) == 1
    review = reviews[0]
    assert review.source == "apple_app_store"
    assert review.app_name == "Spotify"
    assert review.item_id == "324684580"
    assert review.review_id == "111"
    assert review.review_title == "Useful app"
    assert review.rating == 5.0
    assert review.helpful_votes == 3
    assert review.app_version == "9.0.0"
    assert review.country == "us"
