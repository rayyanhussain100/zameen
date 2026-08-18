"""Embedding helper wrapping Google's text-embedding-004.

Produces 768-dim vectors to match the `vector(768)` column and HNSW
(vector_cosine_ops) index in db/schema.sql. If you ever change embedding
model/dimension, you must migrate the column and rebuild the index to match.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from zameen_agent.config import settings

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


def embed_text(text: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Embed a single string. task_type is RETRIEVAL_DOCUMENT for listing text
    stored at scrape time, RETRIEVAL_QUERY for a user's search question."""
    return embed_texts([text], task_type=task_type)[0]


def embed_texts(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Batch-embed strings in a single API call."""
    if not texts:
        return []
    client = _get_client()
    response = client.models.embed_content(
        model=f"models/{settings.embedding_model}",
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return [embedding.values for embedding in response.embeddings]


def listing_embedding_text(title: str | None, description: str | None, location: str | None) -> str:
    """Compose the text that gets embedded for a listing row. Kept as a single
    function so scraper/pipeline.py and any future re-embed script stay in sync."""
    parts = [p for p in (title, location, description) if p]
    return " — ".join(parts)
