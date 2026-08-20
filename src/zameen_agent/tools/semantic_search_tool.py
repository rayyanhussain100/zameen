"""Semantic search tool: embeds a natural-language query and finds the
closest listings by cosine distance over pgvector's HNSW index.
"""

from __future__ import annotations

from zameen_agent.db import get_connection, sanitize_rows
from zameen_agent.embeddings import embed_text

_MAX_TOP_K = 50

# `<=>` is pgvector's cosine-distance operator — must match the index's
# `vector_cosine_ops` opclass (db/schema.sql) for the HNSW index to be used.
_SEARCH_SQL = """
SELECT
    id, source_url, title, purpose, property_type, city, location,
    price_pkr, price_raw, area_marla, area_sqft, bedrooms, bathrooms,
    embedding <=> %(query_embedding)s AS distance
FROM listings
WHERE embedding IS NOT NULL
  AND (%(purpose)s::text IS NULL OR purpose = %(purpose)s)
  AND (%(city)s::text IS NULL OR city ILIKE %(city)s)
ORDER BY embedding <=> %(query_embedding)s
LIMIT %(top_k)s
"""


def semantic_search(
    query: str,
    purpose: str | None = None,
    city: str | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Find listings semantically similar to a natural-language description.

    Use this for fuzzy/descriptive requests that don't map cleanly onto exact
    column filters — e.g. "cozy family home near a park in Lahore", "modern
    apartment with a view for rent", "plot suitable for building a farm
    house". For exact filters/aggregates (price ranges, counts, "cheapest
    3-bed house in DHA"), prefer the sql_query tool instead.

    Embeds `query` with the same model used at scrape time, then does a
    cosine-distance nearest-neighbor search (pgvector, HNSW index) over the
    `listings.embedding` column. Prices are PKR; purpose is 'sale' or 'rent'.

    Args:
        query: Free-text description of what the user is looking for.
        purpose: Optional filter, 'sale' or 'rent'.
        city: Optional city filter (case-insensitive substring match).
        top_k: Number of results to return (default 10, capped at 50).

    Returns:
        A list of listing dicts ordered by similarity (closest first), each
        including a `distance` field (lower = more similar; 0 = identical).
    """
    query_embedding = embed_text(query, task_type="RETRIEVAL_QUERY")
    capped_top_k = max(1, min(top_k, _MAX_TOP_K))

    with get_connection(read_only=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _SEARCH_SQL,
                {
                    "query_embedding": query_embedding,
                    "purpose": purpose,
                    "city": f"%{city}%" if city else None,
                    "top_k": capped_top_k,
                },
            )
            return sanitize_rows(cur.fetchall())
