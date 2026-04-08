"""Resilient HTTP client behavior (mocked transport)."""

import httpx
import pytest

from article_miner.domain.errors import NcbiTransportError
from article_miner.infrastructure.ncbi.config import NcbiClientConfig
from article_miner.infrastructure.ncbi.rate_limiter import RateLimiter
from article_miner.infrastructure.ncbi.resilient_http import ResilientHttpClient


def test_retries_then_succeeds() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0)
    config = NcbiClientConfig(max_retries=5, base_backoff_seconds=0.01)
    http = ResilientHttpClient(config, RateLimiter(1000.0), client=client)
    try:
        assert http.get_text("https://example.test/x", {"a": "1"}) == "ok"
    finally:
        http.close()
    assert attempts["n"] == 3


def test_exhausts_retries_on_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="no")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0)
    config = NcbiClientConfig(max_retries=2, base_backoff_seconds=0.01)
    http = ResilientHttpClient(config, RateLimiter(1000.0), client=client)
    try:
        with pytest.raises(NcbiTransportError):
            http.get_text("https://example.test/x", {})
    finally:
        http.close()


def test_raises_on_400_without_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0)
    config = NcbiClientConfig(max_retries=2)
    http = ResilientHttpClient(config, RateLimiter(1000.0), client=client)
    try:
        with pytest.raises(NcbiTransportError):
            http.get_text("https://example.test/x", {})
    finally:
        http.close()
