#!/usr/bin/env python3
"""Thin launcher for the packaged workflow (same as ``uv run pubmed-workflow``)."""

from article_miner.cli.pubmed_workflow import main

if __name__ == "__main__":
    raise SystemExit(main())
