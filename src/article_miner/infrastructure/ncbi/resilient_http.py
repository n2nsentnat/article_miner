"""HTTP GET with rate limiting, retries, and structured errors."""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from article_miner.domain.errors import NcbiRateLimitError, NcbiTransportError
from article_miner.infrastructure.ncbi.config import NcbiClientConfig
from article_miner.infrastructure.ncbi.rate_limiter import RateLimiter


class ResilientHttpClient:
    """Thin wrapper: rate limit + exponential backoff retries."""

    def __init__(
        self,
        config: NcbiClientConfig,
        rate_limiter: RateLimiter,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._rate = rate_limiter
        self._client = client or httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def get_text(self, url: str, params: dict[str, Any]) -> str:
        """GET and return response body as text (raises domain errors on failure)."""
        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            self._rate.acquire()
            try:
                response = self._client.get(url, params=params)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt >= self._config.max_retries:
                    raise NcbiTransportError(f"HTTP request failed after retries: {exc}") from exc
                self._backoff(attempt, exc)
                continue

            if response.status_code == 429:
                if attempt >= self._config.max_retries:
                    raise NcbiRateLimitError("NCBI returned HTTP 429 (rate limited).")
                self._backoff(attempt, None, extra=response.headers.get("Retry-After"))
                continue

            if response.status_code in (500, 502, 503, 504):
                if attempt >= self._config.max_retries:
                    raise NcbiTransportError(
                        f"NCBI server error HTTP {response.status_code}: {response.text[:500]}"
                    )
                self._backoff(attempt, None)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise NcbiTransportError(
                    f"NCBI HTTP {response.status_code}: {response.text[:500]}"
                ) from exc

            return response.text

        raise NcbiTransportError(f"HTTP request failed: {last_exc!r}")

    def _backoff(self, attempt: int, _exc: Exception | None, extra: str | None = None) -> None:
        base = self._config.base_backoff_seconds * (2**attempt)
        jitter = random.uniform(0, 0.25 * base)
        delay = base + jitter
        if extra:
            try:
                delay = max(delay, float(extra))
            except ValueError:
                pass
        time.sleep(delay)
