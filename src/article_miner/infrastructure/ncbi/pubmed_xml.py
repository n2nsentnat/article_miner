"""Parse PubMed efetch XML into domain Article models."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterable

from article_miner.domain.article import Article, Author
from article_miner.domain.errors import ArticleParseError, MalformedResponseError


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", maxsplit=1)[-1]
    return tag


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    t = (el.text or "").strip()
    return t or None


def _find_text(parent: ET.Element, path: str) -> str | None:
    child = parent.find(path)
    return _text(child)


def _collect_abstract(abstract_el: ET.Element | None) -> str | None:
    if abstract_el is None:
        return None
    parts: list[str] = []
    for child in abstract_el:
        if _local(child.tag) != "AbstractText":
            continue
        label = child.get("Label")
        piece = _text(child) or ""
        if label:
            parts.append(f"{label}: {piece}".strip())
        else:
            parts.append(piece.strip())
    if parts:
        return "\n\n".join(p for p in parts if p)
    return _text(abstract_el)


def _parse_date_container(pub_date: ET.Element | None) -> tuple[int | None, str | None, int | None]:
    if pub_date is None:
        return None, None, None
    year_el = pub_date.find("Year")
    month_el = pub_date.find("Month")
    day_el = pub_date.find("Day")
    year: int | None = None
    day: int | None = None
    if year_el is not None and (year_el.text or "").strip():
        try:
            year = int(year_el.text.strip())  # type: ignore[union-attr]
        except ValueError:
            year = None
    month = _text(month_el)
    if day_el is not None and (day_el.text or "").strip():
        try:
            day = int(day_el.text.strip())  # type: ignore[union-attr]
        except ValueError:
            day = None
    return year, month, day


def _parse_authors(author_list: ET.Element | None) -> list[Author]:
    if author_list is None:
        return []
    authors: list[Author] = []
    for author in author_list:
        if _local(author.tag) != "Author":
            continue
        aff = author.find("AffiliationInfo/Affiliation")
        affiliation = _text(aff)
        authors.append(
            Author(
                last_name=_text(author.find("LastName")),
                fore_name=_text(author.find("ForeName")),
                initials=_text(author.find("Initials")),
                affiliation=affiliation,
            )
        )
    return authors


def _parse_mesh(mesh_heading_list: ET.Element | None) -> list[str]:
    if mesh_heading_list is None:
        return []
    out: list[str] = []
    for mh in mesh_heading_list:
        if _local(mh.tag) != "MeshHeading":
            continue
        parts: list[str] = []
        for child in mh:
            ln = _local(child.tag)
            if ln == "DescriptorName":
                t = _text(child)
                if t:
                    parts.append(t)
            elif ln == "QualifierName":
                t = _text(child)
                if t:
                    parts.append(t)
        if parts:
            out.append(" / ".join(parts))
    return out


def _parse_keywords(keyword_list: ET.Element | None) -> list[str]:
    if keyword_list is None:
        return []
    out: list[str] = []
    for kw in keyword_list:
        if _local(kw.tag) != "Keyword":
            continue
        t = _text(kw)
        if t:
            out.append(t)
    return out


def _parse_publication_types(pub_type_list: ET.Element | None) -> list[str]:
    if pub_type_list is None:
        return []
    out: list[str] = []
    for pt in pub_type_list:
        if _local(pt.tag) != "PublicationType":
            continue
        t = _text(pt)
        if t:
            out.append(t)
    return out


def _article_ids(pubmed_data: ET.Element | None) -> tuple[str | None, str | None]:
    if pubmed_data is None:
        return None, None
    doi: str | None = None
    pmc: str | None = None
    id_list = pubmed_data.find("ArticleIdList")
    if id_list is None:
        return doi, pmc
    for aid in id_list:
        if _local(aid.tag) != "ArticleId":
            continue
        id_type = aid.get("IdType")
        val = _text(aid)
        if not val:
            continue
        if id_type == "doi":
            doi = val
        elif id_type == "pmc":
            pmc = val
    return doi, pmc


def parse_pubmed_article_element(article_el: ET.Element) -> Article:
    """Parse a single PubmedArticle element."""
    if _local(article_el.tag) != "PubmedArticle":
        msg = "Expected PubmedArticle root fragment"
        raise ArticleParseError(msg)

    medline = article_el.find("MedlineCitation")
    if medline is None:
        msg = "Missing MedlineCitation"
        raise ArticleParseError(msg)

    pmid_el = medline.find("PMID")
    pmid = _text(pmid_el)
    if not pmid:
        msg = "Missing PMID"
        raise ArticleParseError(msg)

    art = medline.find("Article")
    title = _find_text(art, "ArticleTitle") if art is not None else None
    abstract = _collect_abstract(art.find("Abstract") if art is not None else None)
    journal = art.find("Journal") if art is not None else None
    journal_full = _find_text(journal, "Title") if journal is not None else None
    journal_iso = _find_text(journal, "ISOAbbreviation") if journal is not None else None
    issue = journal.find("JournalIssue") if journal is not None else None
    pub_date = issue.find("PubDate") if issue is not None else None
    year, month, day = _parse_date_container(pub_date)

    # DOI may appear under Article/ELocationID or PubmedData/ArticleIdList
    doi: str | None = None
    if art is not None:
        for eloc in art.findall("ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = _text(eloc)
                break

    pubmed_data = article_el.find("PubmedData")
    id_doi, pmc = _article_ids(pubmed_data)
    if doi is None:
        doi = id_doi

    lang = _find_text(art, "Language") if art is not None else None
    authors = _parse_authors(art.find("AuthorList") if art is not None else None)
    pub_types = _parse_publication_types(art.find("PublicationTypeList") if art is not None else None)
    mesh = _parse_mesh(medline.find("MeshHeadingList"))
    keywords = _parse_keywords(medline.find("KeywordList"))

    return Article(
        pmid=pmid,
        title=title,
        abstract=abstract,
        journal_full=journal_full,
        journal_iso=journal_iso,
        publication_year=year,
        publication_month=month,
        publication_day=day,
        doi=doi,
        pmc_id=pmc,
        language=lang,
        publication_types=pub_types,
        mesh_terms=mesh,
        keywords=keywords,
        authors=authors,
    )


def parse_pubmed_xml_document(xml_text: str) -> list[Article]:
    """Parse a full PubmedArticleSet document into Article models."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MalformedResponseError(f"Invalid XML from efetch: {exc}") from exc

    articles: list[Article] = []
    for child in root:
        if _local(child.tag) != "PubmedArticle":
            continue
        try:
            articles.append(parse_pubmed_article_element(child))
        except ArticleParseError:
            # Skip records we cannot parse but continue processing others
            continue
    return articles


def iter_pubmed_article_elements(xml_text: str) -> Iterable[ET.Element]:
    """Yield PubmedArticle elements (for testing / streaming-style use)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MalformedResponseError(f"Invalid XML from efetch: {exc}") from exc
    for child in root:
        if _local(child.tag) == "PubmedArticle":
            yield child
