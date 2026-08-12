from __future__ import annotations

import json
from pathlib import Path

import src.steam_probe as steam_probe
from src.config import AppleAppStoreConfig, AppConfig, AmazonConfig, AssessmentConfig, GooglePlayConfig, SteamConfig
from src.models import ProbeResult
from src.steam_probe import parse_steam_reviews, run_steam_probe


FIXTURES = Path(__file__).parent / "fixtures"


def test_steam_json_parsing_normalizes_fields() -> None:
    payload = json.loads((FIXTURES / "steam_reviews.json").read_text(encoding="utf-8"))

    reviews = parse_steam_reviews(payload, "440", "https://example.test", 1, "*")

    assert len(reviews) == 1
    review = reviews[0]
    assert review.source == "steam"
    assert review.item_id == "440"
    assert review.review_id == "1001"
    assert review.recommendation is True
    assert review.helpful_votes == 3
    assert review.playtime_forever == 1200


def test_steam_cursor_can_be_extracted_from_payload() -> None:
    payload = json.loads((FIXTURES / "steam_reviews.json").read_text(encoding="utf-8"))

    assert payload["cursor"] == "AoIIPwYYanVtcA=="


def test_repeated_cursor_detection_state_is_recordable() -> None:
    result = ProbeResult(source="steam", pagination_success=False, cursor_changed_correctly=False)

    assert result.pagination_success is False
    assert result.cursor_changed_correctly is False


def test_duplicate_review_handling_model_summary() -> None:
    result = ProbeResult(source="steam", duplicate_review_ids=["1001"])

    assert result.summary()["duplicate_review_ids"] == ["1001"]


def test_steam_probe_retrieves_multiple_cursor_pages(monkeypatch, tmp_path: Path) -> None:
    payloads = [
        _steam_payload("cursor-1", ["1", "2"]),
        _steam_payload("cursor-2", ["3", "4"]),
        _steam_payload("cursor-3", ["5", "6"]),
        _steam_payload("cursor-1", ["1", "2"]),
        _steam_payload("cursor-2", ["3", "4"]),
        _steam_payload("cursor-3", ["5", "6"]),
    ]

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def __init__(self, payload: dict) -> None:
            self._payload = payload
            self.content = json.dumps(payload).encode("utf-8")
            self.text = json.dumps(payload)

        def json(self) -> dict:
            return self._payload

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            self.index = 0

        def get(self, url: str):
            from src.models import RequestRecord
            from src.http_utils import HttpResult

            payload = payloads[self.index]
            self.index += 1
            return HttpResult(FakeResponse(payload), RequestRecord(url, 200, 0.01, True, "application/json", 10))

    monkeypatch.setattr(steam_probe, "PoliteSession", FakeSession)
    config = AppConfig(
        assessment=AssessmentConfig(max_reviews_per_item=5, max_pages_per_item=5, repeat_runs=2),
        steam=SteamConfig(enabled=True, app_ids=("999",), reviews_per_page=2),
        amazon=AmazonConfig(enabled=False),
        google_play=GooglePlayConfig(enabled=False),
        apple_app_store=AppleAppStoreConfig(enabled=False),
        path=tmp_path / "config.yaml",
    )

    result = run_steam_probe(config, tmp_path)

    assert result.pagination_success is True
    assert result.cursor_changed_correctly is True
    assert len(result.reviews) == 5
    assert result.overlap_across_repeat_runs == 5
    assert result.repeat_run_overlap_rate == 1.0
    assert [batch["request_cursor"] for batch in result.pagination_batches[:3]] == ["*", "cursor-1", "cursor-2"]
    assert result.pagination_batches[1]["distinct_from_previous_page"] is True


def _steam_payload(cursor: str, ids: list[str]) -> dict:
    return {
        "success": 1,
        "cursor": cursor,
        "reviews": [
            {
                "recommendationid": review_id,
                "language": "english",
                "review": f"review {review_id}",
                "timestamp_created": 1700000000,
                "voted_up": True,
                "author": {"steamid": f"author-{review_id}"},
            }
            for review_id in ids
        ],
    }
