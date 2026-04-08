"""Probabilistic duplicate detection for collected PubMed JSON."""

from article_miner.dedup.engine import (
    DedupReport,
    DuplicateCluster,
    build_duplicate_report,
    format_dedup_markdown,
    normalize_doi,
    normalize_title,
)

__all__ = [
    "DedupReport",
    "DuplicateCluster",
    "build_duplicate_report",
    "format_dedup_markdown",
    "normalize_doi",
    "normalize_title",
]
