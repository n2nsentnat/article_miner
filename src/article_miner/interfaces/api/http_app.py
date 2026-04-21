"""FastAPI entry points for collect, dedup, and insight workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from article_miner.application.collect.service import CollectArticlesService
from article_miner.application.dedup.service import (
    build_duplicate_report,
    format_dedup_markdown,
)
from article_miner.application.insight_job import InsightJobConfig, run_insight_job
from article_miner.application.insights.llm_provider_registry import (
    registered_insight_providers,
)
from article_miner.application.insights.report import (
    default_insight_report_path,
    write_insight_report_md,
)
from article_miner.common.env import load_project_env
from article_miner.domain.collect.models import CollectionOutput
from article_miner.domain.insight import InsightJobResult
from article_miner.domain.errors import ArticleMinerError, NcbiError
from article_miner.infrastructure.collect.ncbi_client_config import NcbiClientConfig
from article_miner.infrastructure.collect.pubmed_gateway import EntrezPubMedGateway
from article_miner.infrastructure.collect.rate_limiter import RateLimiter
from article_miner.infrastructure.collect.resilient_http import ResilientHttpClient
from article_miner.interfaces.api.output_paths import (
    is_jsonl_path,
    resolve_collect_path,
    resolve_dedup_path,
    resolve_insight_path,
)
from article_miner.interfaces.api.schemas import (
    CollectRequest,
    DedupApiResponse,
    DedupRequest,
    FileWriteResponse,
    InsightRequest,
)

app = FastAPI(
    title="article-miner",
    description="PubMed collection, duplicate grouping, and LLM insight classification.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_insight_files(
    result: InsightJobResult, out_path: Path, write_report_md: bool
) -> dict[str, str]:
    paths: dict[str, str] = {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if is_jsonl_path(out_path):
        with out_path.open("w", encoding="utf-8") as f:
            for row in result.articles:
                f.write(row.model_dump_json() + "\n")
        paths["jsonl"] = str(out_path.resolve())
        summary_path = out_path.with_suffix(".summary.json")
        _write_text(summary_path, result.model_dump_json(indent=2))
        paths["summary_json"] = str(summary_path.resolve())
    else:
        _write_text(out_path, result.model_dump_json(indent=2))
        paths["json"] = str(out_path.resolve())
    if write_report_md:
        rep_path = default_insight_report_path(out_path)
        write_insight_report_md(result, rep_path, out_path)
        paths["report_md"] = str(rep_path.resolve())
    return paths


@app.post("/collect", response_model=Union[CollectionOutput, FileWriteResponse])
def post_collect(body: CollectRequest) -> Union[CollectionOutput, FileWriteResponse]:
    load_project_env()
    config = NcbiClientConfig(
        api_key=body.api_key, email=body.email, tool=body.tool
    )
    limiter = RateLimiter(config.requests_per_second)
    http = ResilientHttpClient(config, limiter)
    try:
        gateway = EntrezPubMedGateway(http, config)
        service = CollectArticlesService(gateway)
        try:
            result = service.run(query=body.query, requested_count=body.count)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (NcbiError, ArticleMinerError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if body.output_format == "file":
            path = resolve_collect_path(body.output_path)
            try:
                _write_text(
                    path,
                    result.model_dump_json(indent=2, exclude_none=False),
                )
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"Failed to write {path}: {exc}"
                ) from exc
            return FileWriteResponse(paths={"collection_json": str(path)})
        return result
    finally:
        http.close()


@app.post("/dedup", response_model=Union[DedupApiResponse, FileWriteResponse])
def post_dedup(body: DedupRequest) -> Union[DedupApiResponse, FileWriteResponse]:
    report = build_duplicate_report(body.collection)
    md_text = format_dedup_markdown(report) if body.include_markdown else None

    if body.output_format == "file":
        json_path = resolve_dedup_path(body.output_path)
        try:
            _write_text(json_path, report.model_dump_json(indent=2))
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to write {json_path}: {exc}"
            ) from exc
        paths: dict[str, str] = {"report_json": str(json_path.resolve())}
        if body.include_markdown:
            md_path = json_path.with_suffix(".md")
            try:
                _write_text(md_path, format_dedup_markdown(report))
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"Failed to write {md_path}: {exc}"
                ) from exc
            paths["markdown"] = str(md_path.resolve())
        return FileWriteResponse(paths=paths)

    return DedupApiResponse(report=report, markdown=md_text)


@app.post("/insights", response_model=Union[InsightJobResult, FileWriteResponse])
async def post_insights(
    body: InsightRequest,
) -> Union[InsightJobResult, FileWriteResponse]:
    load_project_env()
    try:
        model, extra = body.resolve_model_and_extras()
    except KeyError as exc:
        allowed = ", ".join(registered_insight_providers())
        raise HTTPException(
            status_code=400, detail=f"llm must be one of: {allowed}"
        ) from exc

    cache = Path(body.cache_path) if body.cache_path else None

    config = InsightJobConfig(
        model=model,
        confidence_threshold=body.confidence_threshold,
        concurrency=body.concurrency,
        enable_audit=body.enable_audit,
        cache_path=cache,
        incremental_jsonl_path=None,
        progress=body.progress,
        progress_every=body.progress_every,
        extra_completion_kwargs=extra,
    )

    try:
        result = await run_insight_job(body.collection, config)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if body.output_format == "file":
        out_path = resolve_insight_path(body.output_path, body.insight_file_format)
        try:
            paths = _write_insight_files(
                result, out_path, write_report_md=body.write_report_md
            )
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to write insight output: {exc}"
            ) from exc
        return FileWriteResponse(paths=paths)

    return result


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API with uvicorn (``article-miner-api`` console script)."""
    import uvicorn

    uvicorn.run(
        "article_miner.interfaces.api.http_app:app",
        host=host,
        port=port,
        factory=False,
    )
