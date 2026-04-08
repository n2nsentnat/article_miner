"""Concrete PubMed gateway: ESearch + batched EFetch."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from article_miner.domain.article import Article
from article_miner.domain.errors import MalformedResponseError
from article_miner.infrastructure.ncbi.config import (
    EFETCH_ID_BATCH_SIZE,
    ESEARCH_PAGE_MAX,
    EFETCH_URL,
    ESEARCH_URL,
    NcbiClientConfig,
)
from article_miner.infrastructure.ncbi.esearch_models import ESearchInner, ESearchEnvelope
from article_miner.infrastructure.ncbi.http_port import HttpTextClient
from article_miner.infrastructure.ncbi.pubmed_xml import parse_pubmed_xml_document


_ERROR_TAG = re.compile(r"<ERROR\b", re.IGNORECASE)


class EntrezPubMedGateway:
    """NCBI E-utilities implementation of ``PubMedGateway``."""

    def __init__(self, http: HttpTextClient, config: NcbiClientConfig) -> None:
        self._http = http
        self._config = config

    def _common_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "tool": self._config.tool,
        }
        if self._config.api_key:
            params["api_key"] = self._config.api_key
        if self._config.email:
            params["email"] = self._config.email
        return params

    def search_pmids(self, query: str, max_results: int) -> tuple[int, list[str]]:
        all_ids: list[str] = []
        retstart = 0
        total_count = 0

        while len(all_ids) < max_results:
            remaining = max_results - len(all_ids)
            retmax = min(ESEARCH_PAGE_MAX, remaining)
            params = {
                **self._common_params(),
                "term": query,
                "retstart": retstart,
                "retmax": retmax,
                "retmode": "json",
            }
            body = self._http.get_text(ESEARCH_URL, params)
            inner = self._parse_esearch_json(body)
            total_count = int(inner.count)
            idlist = list(inner.idlist)
            cap = min(max_results, total_count)
            all_ids.extend(idlist)
            if len(all_ids) >= cap:
                return total_count, all_ids[:cap]
            if not idlist:
                break
            if len(idlist) < retmax:
                break
            retstart += len(idlist)

        cap = min(max_results, total_count) if total_count else len(all_ids)
        return total_count, all_ids[:cap]

    def fetch_articles(self, pmids: list[str]) -> tuple[list[Article], list[str]]:
        if not pmids:
            return [], []

        by_pmid: dict[str, Article] = {}
        warnings: list[str] = []

        for i in range(0, len(pmids), EFETCH_ID_BATCH_SIZE):
            batch = pmids[i : i + EFETCH_ID_BATCH_SIZE]
            params = {
                **self._common_params(),
                "id": ",".join(batch),
                "retmode": "xml",
            }
            xml_text = self._http.get_text(EFETCH_URL, params)
            self._raise_if_efetch_error(xml_text)
            parsed = parse_pubmed_xml_document(xml_text)
            for article in parsed:
                by_pmid[article.pmid] = article

        ordered: list[Article] = []
        for pid in pmids:
            article = by_pmid.get(pid)
            if article is None:
                warnings.append(f"No parseable article returned for PMID {pid}.")
            else:
                ordered.append(article)

        return ordered, warnings

    def _parse_esearch_json(self, body: str) -> ESearchInner:
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MalformedResponseError(f"ESearch returned invalid JSON: {exc}") from exc
        try:
            envelope = ESearchEnvelope.model_validate(data)
        except ValidationError as exc:
            raise MalformedResponseError(f"ESearch JSON failed validation: {exc}") from exc
        return envelope.esearchresult

    @staticmethod
    def _raise_if_efetch_error(xml_text: str) -> None:
        if _ERROR_TAG.search(xml_text):
            # Extract first ERROR text if possible
            m = re.search(r"<ERROR[^>]*>([^<]+)</ERROR>", xml_text, re.IGNORECASE | re.DOTALL)
            detail = m.group(1).strip() if m else "unknown error"
            raise MalformedResponseError(f"EFetch returned ERROR: {detail}")
