from __future__ import annotations

import json
from pathlib import Path

from src.google_play_probe import parse_google_play_reviews


FIXTURES = Path(__file__).parent / "fixtures"


def test_google_play_parser_normalizes_fields() -> None:
    records = json.loads((FIXTURES / "google_play_reviews.json").read_text(encoding="utf-8"))

    reviews = parse_google_play_reviews(
        records,
        package_id="com.spotify.music",
        app_name="Spotify",
        country="us",
        language="en",
        source_url="https://example.test/google",
        page_number=1,
        raw_cursor="token-1",
    )

    assert len(reviews) == 1
    review = reviews[0]
    assert review.source == "google_play"
    assert review.app_name == "Spotify"
    assert review.package_id == "com.spotify.music"
    assert review.review_id == "gp-1"
    assert review.rating == 4.0
    assert review.helpful_votes == 12
    assert review.app_version == "8.9.0"
    assert review.developer_response == "Thanks for the feedback."
    assert review.raw_cursor == "token-1"
