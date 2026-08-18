"""Polite HTTP client for scraping Zameen.com.

- Honors robots.txt via urllib.robotparser.
- Enforces a configurable minimum delay + random jitter between requests to
  the same host.
- Retries transient failures (timeouts, 5xx, connection errors) with
  exponential backoff via tenacity.

No headless browser and no third-party scraping service by design — this is
a plain httpx.Client hitting server-rendered pages directly.
"""

from __future__ import annotations

import random
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from zameen_agent.config import settings


class RobotsDisallowedError(Exception):
    """Raised when robots.txt disallows fetching a URL for our user agent."""


class RobotsChecker:
    """Fetches and caches robots.txt per host, then answers can_fetch()."""

    def __init__(self, user_agent: str, http_client: httpx.Client) -> None:
        self._user_agent = user_agent
        self._http_client = http_client
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._parsers:
            robots_url = f"{host}/robots.txt"
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                response = self._http_client.get(robots_url, timeout=10.0)
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:
                    # No robots.txt (or blocked) — default to allow-all, per
                    # standard robots.txt semantics for a missing file.
                    parser.parse([])
            except httpx.HTTPError:
                parser.parse([])
            self._parsers[host] = parser
        return self._parsers[host]

    def can_fetch(self, url: str) -> bool:
        return self._parser_for(url).can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        delay = self._parser_for(url).crawl_delay(self._user_agent)
        return float(delay) if delay is not None else None


class PoliteHTTPClient:
    """httpx-based client that rate-limits, respects robots.txt, and retries."""

    def __init__(
        self,
        *,
        user_agent: str = settings.user_agent,
        min_delay_seconds: float = settings.min_delay_seconds,
        jitter_seconds: float = settings.jitter_seconds,
        max_retries: int = settings.max_retries,
        timeout: float = 15.0,
    ) -> None:
        self._min_delay_seconds = min_delay_seconds
        self._jitter_seconds = jitter_seconds
        self._max_retries = max_retries
        self._last_request_at: dict[str, float] = {}

        self._http_client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )
        self._robots = RobotsChecker(user_agent, self._http_client)

    def __enter__(self) -> "PoliteHTTPClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http_client.close()

    def _wait_for_rate_limit(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is None:
            return
        elapsed = time.monotonic() - last
        delay = self._min_delay_seconds + random.uniform(0, self._jitter_seconds)
        remaining = delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str) -> httpx.Response:
        """Fetch a URL, honoring robots.txt and this client's rate limit."""
        if not self._robots.can_fetch(url):
            raise RobotsDisallowedError(f"robots.txt disallows fetching: {url}")

        host = urlparse(url).netloc
        self._wait_for_rate_limit(host)

        response = self._get_with_retry(url)
        self._last_request_at[host] = time.monotonic()
        return response

    def _get_with_retry(self, url: str) -> httpx.Response:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=60),
            retry=retry_if_exception_type((httpx.TransportError, _RetryableStatusError)),
        )
        def _do_get() -> httpx.Response:
            response = self._http_client.get(url)
            if response.status_code >= 500 or response.status_code == 429:
                raise _RetryableStatusError(response.status_code)
            response.raise_for_status()
            return response

        return _do_get()


class _RetryableStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"retryable HTTP status: {status_code}")
        self.status_code = status_code
