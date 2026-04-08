"""Protocol for HTTP text GET (testability / DIP)."""

from __future__ import annotations

from typing import Any, Protocol


class HttpTextClient(Protocol):
    """Minimal surface used by ``EntrezPubMedGateway``."""

    def get_text(self, url: str, params: dict[str, Any]) -> str:
        """Perform GET with query params and return decoded body text."""
