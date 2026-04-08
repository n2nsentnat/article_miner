"""Tests for PubMed XML parsing."""

import pytest

from article_miner.domain.errors import MalformedResponseError
from article_miner.infrastructure.ncbi.pubmed_xml import (
    parse_pubmed_article_element,
    parse_pubmed_xml_document,
)


def test_parse_minimal_document(minimal_pubmed_xml: str) -> None:
    articles = parse_pubmed_xml_document(minimal_pubmed_xml)
    assert len(articles) == 1
    a = articles[0]
    assert a.pmid == "99999999"
    assert a.title == "Example title for unit tests."
    assert "BACKGROUND: Background text." in (a.abstract or "")
    assert "Second paragraph." in (a.abstract or "")
    assert a.journal_full == "Test Journal Full"
    assert a.journal_iso == "Test J"
    assert a.publication_year == 2024
    assert a.doi == "10.1000/example"
    assert a.keywords == ["k1"]
    assert len(a.authors) == 1
    assert a.authors[0].last_name == "Doe"
    assert a.authors[0].fore_name == "Jane"


def test_parse_invalid_xml_raises() -> None:
    with pytest.raises(MalformedResponseError):
        parse_pubmed_xml_document("not xml")
