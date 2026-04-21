"""HTTP request bodies for the REST API (domain models stay in ``domain``)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from article_miner.application.dedup.service import DedupReport
from article_miner.application.insights.llm_provider_registry import (
    resolve_insight_llm_provider,
    registered_insight_providers,
)
from article_miner.domain.collect.models import CollectionOutput

OutputFormat = Literal["json", "file"]
InsightFileFormat = Literal["json", "jsonl"]

DEFAULT_API_OUTPUT_SUBDIR = Path("article_miner_output")


class FileWriteResponse(BaseModel):
    """Acknowledgement when ``output_format`` is ``file`` (payload written on the server)."""

    output_format: Literal["file"] = Field(
        "file",
        description="Response carries file paths only; full results are on disk.",
    )
    paths: dict[str, str] = Field(
        ...,
        description="Logical key → absolute path on the server host.",
    )


class CollectRequest(BaseModel):
    """PubMed collection parameters."""

    query: str = Field(..., min_length=1, description="PubMed search query (Entrez syntax).")
    count: int = Field(100, ge=1, description="Maximum number of articles to retrieve.")
    api_key: str | None = Field(None, description="NCBI API key (or set NCBI_API_KEY).")
    email: str | None = Field(None, description="Contact email for NCBI etiquette.")
    tool: str = Field("article_miner", min_length=1, description="Tool name sent to NCBI.")
    output_format: OutputFormat = Field(
        "json",
        description="``json`` return body; ``file`` write JSON to ``output_path`` or default.",
    )
    output_path: str | None = Field(
        None,
        description="Server path for collection JSON when ``output_format`` is ``file``.",
    )


class DedupRequest(BaseModel):
    """JSON body with a ``collection`` field for duplicate detection."""

    collection: CollectionOutput
    include_markdown: bool = Field(
        False,
        description="Include Markdown summary (in JSON response or as a sibling file).",
    )
    output_format: OutputFormat = Field(
        "json",
        description="``json`` return body; ``file`` write report (and optional .md) to disk.",
    )
    output_path: str | None = Field(
        None,
        description="Server path for dedup JSON when ``output_format`` is ``file``.",
    )


class InsightRequest(BaseModel):
    """Insight job: a collection plus LiteLLM / job settings."""

    collection: CollectionOutput
    llm: str | None = Field(
        None,
        description=(
            "Provider shortcut (model from env): "
            + ", ".join(registered_insight_providers())
        ),
    )
    model: str | None = Field(
        None,
        description="Direct LiteLLM model id; used when ``llm`` is not set.",
    )
    concurrency: int = Field(8, ge=1, le=64)
    enable_audit: bool = True
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0)
    cache_path: str | None = Field(
        None, description="Optional SQLite cache path on the server filesystem."
    )
    progress: bool = Field(False, description="Enable periodic progress logs (usually off for APIs).")
    progress_every: int = Field(1, ge=1)
    extra_completion_kwargs: dict[str, Any] = Field(default_factory=dict)
    output_format: OutputFormat = Field(
        "json",
        description="``json`` return body; ``file`` write results to ``output_path`` or default.",
    )
    output_path: str | None = Field(
        None,
        description="Server path for insights output when ``output_format`` is ``file``.",
    )
    insight_file_format: InsightFileFormat = Field(
        "json",
        description="Machine-readable file layout when writing (matches CLI).",
    )
    write_report_md: bool = Field(
        True,
        description="When writing files, also write Markdown report next to main output.",
    )

    def resolve_model_and_extras(self) -> tuple[str, dict[str, Any]]:
        """Return LiteLLM model id and merged completion kwargs."""
        provider = (self.llm or "").strip().lower()
        if provider:
            resolution = resolve_insight_llm_provider(provider, os.environ)
            merged = {**resolution.extra_completion_kwargs, **self.extra_completion_kwargs}
            return resolution.model, merged
        if self.model:
            return self.model, dict(self.extra_completion_kwargs)
        default = os.environ.get("INSIGHT_MODEL_OPENAI", "gpt-4o-mini")
        return default, dict(self.extra_completion_kwargs)


class DedupApiResponse(BaseModel):
    """Structured duplicate report plus optional Markdown summary."""

    report: DedupReport
    markdown: str | None = None
