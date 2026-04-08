"""Shared fixtures."""

import pytest


@pytest.fixture()
def minimal_pubmed_xml() -> str:
    """Single-article PubmedArticleSet matching NCBI efetch (no namespace)."""
    return """<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">99999999</PMID>
    <Article PubModel="Print-Electronic">
      <Journal>
        <Title>Test Journal Full</Title>
        <ISOAbbreviation>Test J</ISOAbbreviation>
        <JournalIssue CitedMedium="Internet">
          <PubDate><Year>2024</Year><Month>Jan</Month><Day>15</Day></PubDate>
        </JournalIssue>
      </Journal>
      <ArticleTitle>Example title for unit tests.</ArticleTitle>
      <Abstract>
        <AbstractText Label="BACKGROUND">Background text.</AbstractText>
        <AbstractText>Second paragraph.</AbstractText>
      </Abstract>
      <AuthorList CompleteYN="Y">
        <Author ValidYN="Y">
          <LastName>Doe</LastName>
          <ForeName>Jane</ForeName>
          <Initials>J</Initials>
          <AffiliationInfo><Affiliation>Example University.</Affiliation></AffiliationInfo>
        </Author>
      </AuthorList>
      <Language>eng</Language>
      <PublicationTypeList>
        <PublicationType UI="D016428">Journal Article</PublicationType>
      </PublicationTypeList>
    </Article>
    <KeywordList Owner="NASA">
      <Keyword MajorTopicYN="N">k1</Keyword>
    </KeywordList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">99999999</ArticleId>
      <ArticleId IdType="doi">10.1000/example</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""
