"""Collect PubMed JSON, then run duplicate detection (same stack as the shell workflow)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from article_miner.application.collect_articles import CollectArticlesService
from article_miner.domain.errors import ArticleMinerError, NcbiError
from article_miner.dedup.engine import build_duplicate_report, format_dedup_markdown
from article_miner.infrastructure.ncbi.config import NcbiClientConfig
from article_miner.infrastructure.ncbi.pubmed_gateway import EntrezPubMedGateway
from article_miner.infrastructure.ncbi.rate_limiter import RateLimiter
from article_miner.infrastructure.ncbi.resilient_http import ResilientHttpClient


def _default_output_root() -> Path:
    """Prefer repo root (``pyproject.toml`` in cwd); else walk up from this file; else cwd."""
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").is_file():
        return cwd
    here = Path(__file__).resolve()
    for d in [here.parent] + list(here.parents):
        if (d / "pyproject.toml").is_file():
            return d
    return cwd


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Collect PubMed articles to JSON, then write duplicate report (JSON + Markdown).",
    )
    p.add_argument(
        "query",
        nargs="+",
        help="PubMed / Entrez search query (multiple words allowed)",
    )
    p.add_argument(
        "-n",
        "--count",
        type=int,
        default=100,
        help="Maximum articles to retrieve (default: 100)",
    )
    p.add_argument(
        "-d",
        "--dir",
        type=Path,
        default=None,
        help="Output directory (default: workflow_YYYYMMDD_HHMMSS under project root or cwd)",
    )
    p.add_argument(
        "--tool",
        default=os.environ.get("NCBI_TOOL", "article_miner"),
        help="Tool name for NCBI (default: article_miner or NCBI_TOOL)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    query = " ".join(args.query).strip()
    if not query:
        print("error: QUERY is empty", file=sys.stderr)
        return 2

    root = _default_output_root()
    if args.dir is None:
        out_dir = root / f"workflow_{datetime.now():%Y%m%d_%H%M%S}"
    else:
        out_dir = Path(args.dir).expanduser().resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    articles_path = out_dir / "articles.json"
    dupes_json = out_dir / "dupes.json"
    dupes_md = out_dir / "dupes.md"

    config = NcbiClientConfig(
        api_key=os.environ.get("NCBI_API_KEY"),
        email=os.environ.get("NCBI_EMAIL"),
        tool=args.tool,
    )
    limiter = RateLimiter(config.requests_per_second)
    http = ResilientHttpClient(config, limiter)
    try:
        gateway = EntrezPubMedGateway(http, config)
        service = CollectArticlesService(gateway)
        try:
            result = service.run(query=query, requested_count=args.count)
        except ValidationError as exc:
            print(f"Validation error: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (NcbiError, ArticleMinerError) as exc:
            print(f"PubMed/NCBI error: {exc}", file=sys.stderr)
            return 1

        try:
            articles_path.write_text(
                result.model_dump_json(indent=2, exclude_none=False),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"Failed to write {articles_path}: {exc}", file=sys.stderr)
            return 1

        report = build_duplicate_report(result)
        dupes_json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        dupes_md.write_text(format_dedup_markdown(report), encoding="utf-8")
    finally:
        http.close()

    print(f"Done. Output directory: {out_dir}")
    print(f"  articles: {articles_path}")
    print(f"  dupes JSON: {dupes_json}")
    print(f"  dupes Markdown: {dupes_md}")
    return 0


def run() -> None:
    """Console entry point (``pubmed-workflow``)."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
