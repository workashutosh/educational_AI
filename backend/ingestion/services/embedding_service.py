"""
Local embeddings via FastEmbed (ONNX Runtime) — offline, no API key, no
rate limits, no torch. Deliberately not Gemini/OpenAI: indexing and
retrieval must not depend on any external LLM provider's quota.

Model is swappable via EMBEDDING_MODEL (see config/settings.py) without any
code change — the engine is keyed by model name and rebuilt if it changes.
"""
from __future__ import annotations

import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_engine = None
_engine_model_name: str | None = None

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def model_name() -> str:
    return getattr(settings, "EMBEDDING_MODEL", DEFAULT_MODEL)


def _get_engine():
    global _engine, _engine_model_name
    name = model_name()
    if _engine is not None and _engine_model_name == name:
        return _engine

    with _lock:
        if _engine is not None and _engine_model_name == name:
            return _engine
        from fastembed import TextEmbedding

        logger.info("Loading embedding model %s (first call only)…", name)
        _engine = TextEmbedding(model_name=name)
        _engine_model_name = name
        return _engine


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed passages for storage. One vector per input text, same order."""
    if not texts:
        return []
    engine = _get_engine()
    return [vector.tolist() for vector in engine.embed(texts)]


def embed_query(text: str) -> list[float]:
    """
    Embed a single search query. BGE-family models are asymmetric — queries
    need a different instruction prefix than passages for best retrieval
    quality — so this uses query_embed when the engine supports it, falling
    back to embed() for models/versions that don't distinguish.
    """
    engine = _get_engine()
    query_embed = getattr(engine, "query_embed", None)
    if callable(query_embed):
        return next(iter(query_embed([text]))).tolist()
    return next(iter(engine.embed([text]))).tolist()
