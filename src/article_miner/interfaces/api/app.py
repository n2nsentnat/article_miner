"""Backward-compatible module path for Uvicorn: ``article_miner.interfaces.api.app:app``.

Implementation lives in :mod:`article_miner.interfaces.api.http_app`.
"""

from article_miner.interfaces.api.http_app import app, run

__all__ = ["app", "run"]
