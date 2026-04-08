"""Ports (interfaces) — application depends on abstractions, not NCBI details."""

from __future__ import annotations

from typing import Protocol

from article_miner.domain.article import Article


class PubMedGateway(Protocol):
    """Abstract access to PubMed search + fetch (E-utilities)."""

    def search_pmids(self, query: str, max_results: int) -> tuple[int, list[str]]:
        """Return (total_match_count, pmids in relevance order, truncated to max_results)."""

    def fetch_articles(self, pmids: list[str]) -> tuple[list[Article], list[str]]:
        """Return (articles in PMID order, warnings)."""
