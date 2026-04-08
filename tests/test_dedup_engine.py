"""Tests for PubMed JSON duplicate detection."""

from __future__ import annotations

from article_miner.domain.article import Article, CollectionOutput
from article_miner.dedup.engine import (
    build_duplicate_report,
    normalize_doi,
    normalize_title,
)


def _collection(articles: list[Article], **kwargs: object) -> CollectionOutput:
    return CollectionOutput(
        query="q",
        total_match_count=len(articles),
        requested_count=len(articles),
        retrieved_count=len(articles),
        articles=articles,
        warnings=[],
        **kwargs,
    )


def test_normalize_doi_strips_prefix() -> None:
    assert normalize_doi("https://doi.org/10.1000/abc") == "10.1000/abc"
    assert normalize_doi("DOI:10.1000/abc") == "10.1000/abc"
    assert normalize_doi("doi:10.1000/abc") == "10.1000/abc"


def test_normalize_title_strips_punctuation() -> None:
    assert normalize_title("Hello, World!") == "hello world"
    assert normalize_title(None) == ""


def test_same_doi_clusters() -> None:
    a1 = Article(
        pmid="1",
        title="Same paper",
        doi="10.1234/x",
        publication_year=2020,
    )
    a2 = Article(
        pmid="2",
        title="Same paper variant",
        doi="https://doi.org/10.1234/x",
        publication_year=2020,
    )
    a3 = Article(pmid="3", title="Other", doi="10.999/y", publication_year=2021)
    r = build_duplicate_report(_collection([a1, a2, a3]))
    assert r.duplicate_group_count == 1
    assert r.clusters[0].pmids == ["1", "2"]
    assert r.clusters[0].primary_reason == "same_doi"
    assert r.clusters[0].confidence == "high"


def test_same_normalized_title_and_year() -> None:
    a1 = Article(
        pmid="10",
        title="Effect of X on Y: A Trial.",
        publication_year=2019,
    )
    a2 = Article(
        pmid="11",
        title="Effect of X on Y: A Trial",  # punctuation difference only
        publication_year=2019,
    )
    r = build_duplicate_report(_collection([a1, a2]))
    assert r.duplicate_group_count == 1
    assert set(r.clusters[0].pmids) == {"10", "11"}
    assert r.clusters[0].primary_reason == "same_normalized_title_and_year"


def test_singletons_no_cluster() -> None:
    a = Article(pmid="99", title="Unique title here", publication_year=2024)
    r = build_duplicate_report(_collection([a]))
    assert r.duplicate_group_count == 0
    assert r.clusters == []


def test_retraction_note() -> None:
    a1 = Article(
        pmid="1",
        title="Retraction: Previous study on X",
        publication_year=2022,
    )
    a2 = Article(
        pmid="2",
        title="Retraction: Previous study on X",
        publication_year=2022,
    )
    r = build_duplicate_report(_collection([a1, a2]))
    assert r.clusters[0].reviewer_notes


def test_large_input_linear_stats() -> None:
    """Ensure blocking keeps fuzzy work bounded (smoke: 500 articles, unique titles)."""
    arts = [
        Article(
            pmid=str(30000 + i),
            title=f"Study id {i} unique biomarker long title for blocking test",
            publication_year=2020,
        )
        for i in range(500)
    ]
    r = build_duplicate_report(_collection(arts))
    assert r.duplicate_group_count == 0
    # Should not compare millions of pairs
    assert int(r.stats.get("fuzzy_pairs_compared", 0)) < 500_000
