from __future__ import annotations

import json

import pytest

import src.apple_live_persistence as live
from src.apple_live_persistence import LiveAppleSettings, request_status, run_live_apple_persistence, unique_run_name
from src.database_ingestion import raw_apple_entries
from src.http_utils import HttpResult
from src.models import RequestRecord


def test_raw_entries_preserve_metadata_malformed_and_reviews() -> None:
    payload = {"feed": {"entry": [
        {"id": {"label": "metadata"}},
        "malformed",
        {"im:rating": {"label": "5"}},
        {"id": {"label": "review-1"}, "im:rating": {"label": "5"}},
    ]}}

    entries = raw_apple_entries(payload)

    assert len(entries) == 4
    assert [entry[3] for entry in entries] == ["non_review_entry", "parse_error", "parse_error", "parsed"]
    assert entries[-1][2] == "review-1"
    assert entries[1][1] == "malformed"


@pytest.mark.parametrize("field,value", [
    ("passes", 3),
    ("max_pages_per_pass", 3),
    ("max_requests", 5),
    ("max_normalized_reviews", 101),
    ("request_delay_seconds", 0.5),
])
def test_live_settings_reject_broad_collection_scope(field: str, value: object) -> None:
    values = {"database_url": "postgresql://example", field: value}
    with pytest.raises(ValueError):
        LiveAppleSettings(**values).validated()


def test_live_run_names_are_unique_and_auditable() -> None:
    first = unique_run_name()
    second = unique_run_name()
    assert first.startswith("apple-live-")
    assert second.startswith("apple-live-")
    assert first != second


@pytest.mark.parametrize(("success", "response_present", "page", "code", "parse_error", "count", "expected"), [
    (True, True, 1, 200, None, 2, "ok"),
    (True, True, 1, 200, None, 0, "empty_page"),
    (False, False, 1, None, None, 0, "request_failed"),
    (False, True, 2, 404, None, 0, "pagination_limit_or_unavailable_page"),
    (True, True, 1, 200, "bad JSON", 0, "json_parse_error"),
])
def test_request_outcome_categories(success, response_present, page, code, parse_error, count, expected) -> None:
    record = RequestRecord("test://apple", code, 0.1, success)
    assert request_status(record, response_present, page, parse_error, count) == expected


def test_settings_do_not_serialize_database_url_into_safe_config() -> None:
    settings = LiveAppleSettings(database_url="postgresql://user:secret@example/db")
    serialized = json.dumps({key: value for key, value in settings.__dict__.items() if key != "database_url"}, default=str)
    assert "secret" not in serialized


def test_mocked_live_path_preserves_repeats_malformed_metadata_and_cap(monkeypatch, tmp_path) -> None:
    payload = {"feed": {"entry": [
        {"id": {"label": "metadata"}},
        {"id": {"label": "r1"}, "title": {"label": "One"}, "content": {"label": "Body one is useful"},
         "im:rating": {"label": "5"}, "updated": {"label": "2026-07-17T00:00:00Z"}},
        {"id": {"label": "r2"}, "title": {"label": "Two"}, "content": {"label": "Body two is useful"},
         "im:rating": {"label": "4"}, "updated": {"label": "2026-07-17T00:00:00Z"}},
        "malformed",
    ]}}
    fake_store = _RecordingStore()
    monkeypatch.setattr(live.psycopg, "connect", lambda *_: _FakeConnection())
    monkeypatch.setattr(live, "IngestionStore", lambda conn: fake_store)
    monkeypatch.setattr(live, "reconcile_run", lambda *_: {
        "raw_review_appearances": len(fake_store.raw),
        "normalized_reviews": fake_store.normalized,
        "observation_statuses": fake_store.observations,
        "final_run_status": fake_store.final_status,
    })
    settings = LiveAppleSettings(database_url="postgresql://unused", output_root=tmp_path,
                                 run_name="apple-live-unit-test", max_normalized_reviews=1)

    report = run_live_apple_persistence(settings, session=_FakeSession(payload))

    assert report["raw_review_appearances"] == 8
    assert report["normalized_reviews"] == 1
    assert fake_store.observations == {
        "non_review_entry": 2, "new": 1, "excluded": 1, "parse_error": 2, "repeat_seen": 2,
    }
    assert fake_store.missing == ["normalization_cap_exceeded"]
    assert len(list((tmp_path / "data" / "raw" / "apple_live" / settings.run_name).glob("*.json"))) == 2


def test_late_malformed_page_makes_cap_reached_run_partial(monkeypatch, tmp_path) -> None:
    payload = {"feed": {"entry": [{
        "id": {"label": "r1"}, "content": {"label": "Useful review body"},
        "im:rating": {"label": "5"}, "updated": {"label": "2026-07-17T00:00:00Z"},
    }]}}
    fake_store = _RecordingStore()
    monkeypatch.setattr(live.psycopg, "connect", lambda *_: _FakeConnection())
    monkeypatch.setattr(live, "IngestionStore", lambda conn: fake_store)
    monkeypatch.setattr(live, "reconcile_run", lambda *_: {"final_run_status": fake_store.final_status})
    settings = LiveAppleSettings(database_url="postgresql://unused", output_root=tmp_path,
                                 run_name="apple-live-late-failure", max_normalized_reviews=1)

    report = run_live_apple_persistence(settings, session=_SequenceSession([
        json.dumps(payload).encode(), b"not-json",
    ]))

    assert report["final_run_status"] == "partial"
    assert "json_parse_error" in fake_store.missing


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def commit(self) -> None:
        pass


class _FakeSession:
    def __init__(self, payload: dict) -> None:
        self.content = json.dumps(payload).encode()

    def get(self, url: str) -> HttpResult:
        response = type("Response", (), {"content": self.content})()
        return HttpResult(response, RequestRecord(url, 200, 0.01, True, "application/json", len(self.content)))


class _SequenceSession:
    def __init__(self, contents: list[bytes]) -> None:
        self.contents = iter(contents)

    def get(self, url: str) -> HttpResult:
        content = next(self.contents)
        response = type("Response", (), {"content": content})()
        return HttpResult(response, RequestRecord(url, 200, 0.01, True, "application/json", len(content)))


class _RecordingStore:
    def __init__(self) -> None:
        self.raw = []
        self.identities = set()
        self.normalized = 0
        self.observations: dict[str, int] = {}
        self.missing: list[str] = []
        self.final_status = "running"

    def ensure_apple_source(self): return "source"
    def create_run(self, *args, **kwargs): return "run"
    def resolve_target(self, *args, **kwargs): return "target", "context"
    def add_request(self, *args, **kwargs): return f"request-{args[1]}"
    def add_payload(self, *args, **kwargs): return f"payload-{args[0]}"

    def add_raw_record(self, payload_id, ordinal, entry, review_id, parse_status, parse_error):
        raw_id = f"{payload_id}-{ordinal}"
        self.raw.append((raw_id, entry, parse_status))
        return raw_id

    def add_non_normalized_observation(self, raw_id, status, observed_at, identity_id=None):
        self.observations[status] = self.observations.get(status, 0) + 1

    def resolve_identity(self, context, review_id, observed_at):
        is_new = review_id not in self.identities
        self.identities.add(review_id)
        return review_id, is_new

    def add_normalized(self, *args, **kwargs):
        self.normalized += 1
        self.observations["new"] = self.observations.get("new", 0) + 1

    def add_missing_evidence(self, target, reason, *args, **kwargs):
        self.missing.append(reason)

    def finalize(self, run, target, count, target_reached, status, reason):
        self.final_status = status
