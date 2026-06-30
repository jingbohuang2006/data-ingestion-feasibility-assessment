"""Small, polite HTTP helper for feasibility probes."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from .models import RequestRecord

LOGGER = logging.getLogger(__name__)


STEAM_USER_AGENT = "review-feasibility-assessment/0.1 academic technical test"
AMAZON_USER_AGENT = "review-feasibility-assessment/0.1 small academic feasibility test"
BLOCK_STATUS_CODES = {401, 403, 429}
TRANSIENT_STATUS_CODES = {500, 502, 503, 504}


@dataclass
class HttpResult:
    """Response plus request metadata."""

    response: requests.Response | None
    record: RequestRecord


class PoliteSession:
    """Requests session with fixed delay and limited transient retries."""

    def __init__(self, timeout_seconds: float, delay_seconds: float, user_agent: str) -> None:
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last_request_at: float | None = None

    def get(self, url: str, **kwargs: Any) -> HttpResult:
        """Perform a GET and return safe request metadata."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.delay_seconds:
                time.sleep(self.delay_seconds - elapsed)

        attempts = 0
        last_result: HttpResult | None = None
        while attempts < 2:
            attempts += 1
            started = time.monotonic()
            try:
                response = self.session.get(url, timeout=self.timeout_seconds, **kwargs)
                elapsed_seconds = time.monotonic() - started
                self._last_request_at = time.monotonic()
                record = RequestRecord(
                    url=url,
                    status_code=response.status_code,
                    elapsed_seconds=elapsed_seconds,
                    success=200 <= response.status_code < 300,
                    content_type=response.headers.get("content-type"),
                    response_size=len(response.content or b""),
                    blocked=response.status_code in BLOCK_STATUS_CODES,
                )
                LOGGER.info("GET %s -> %s in %.2fs", scrub_url(url), response.status_code, elapsed_seconds)
                result = HttpResult(response=response, record=record)
                last_result = result
                if response.status_code in TRANSIENT_STATUS_CODES and attempts < 2:
                    continue
                return result
            except requests.RequestException as exc:
                elapsed_seconds = time.monotonic() - started
                self._last_request_at = time.monotonic()
                record = RequestRecord(
                    url=url,
                    status_code=None,
                    elapsed_seconds=elapsed_seconds,
                    success=False,
                    error=str(exc),
                )
                LOGGER.warning("GET %s failed: %s", scrub_url(url), exc)
                last_result = HttpResult(response=None, record=record)
                return last_result
        return last_result or HttpResult(
            response=None,
            record=RequestRecord(url=url, status_code=None, elapsed_seconds=None, success=False, error="unknown"),
        )


def scrub_url(url: str) -> str:
    """Avoid logging query values that might contain temporary tokens."""
    if "?" not in url:
        return url
    return url.split("?", 1)[0] + "?..."


def load_optional_amazon_auth() -> tuple[dict[str, str], dict[str, str]]:
    """Load optional Amazon headers and cookies from environment variables."""
    return _load_json_mapping("AMAZON_HEADERS_JSON"), _load_json_mapping("AMAZON_COOKIES_JSON")


def _load_json_mapping(env_name: str) -> dict[str, str]:
    value = os.environ.get(env_name)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{env_name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{env_name} must be a JSON object")
    return {str(key): str(item) for key, item in parsed.items()}
