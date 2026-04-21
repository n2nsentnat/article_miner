"""HTTP API (FastAPI) entry points."""

from article_miner.interfaces.api.app import app, run

__all__ = ["app", "run"]
