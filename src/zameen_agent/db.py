"""Postgres connection helper.

Thin wrapper over psycopg (v3) — no ORM. Registers the pgvector adapter so
`vector` columns round-trip as pgvector.Vector objects (accepted directly as
query parameters; see sanitize_rows() for turning them back into plain lists
when returning query results out of the process, e.g. from an agent tool).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from pgvector import Vector
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector

from zameen_agent.config import settings


@contextmanager
def get_connection(*, read_only: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection with the pgvector type registered.

    Commits on clean exit, rolls back on exception. Pass read_only=True to
    additionally mark the transaction read-only at the Postgres level (used
    by the SQL tool as a second line of defense beyond the query-text guard).
    """
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    try:
        register_vector(conn)
        if read_only:
            conn.execute("SET TRANSACTION READ ONLY")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json_safe(value: Any) -> Any:
    # NUMERIC columns (price_pkr, area_marla, area_sqft, ...) round-trip as
    # Decimal via psycopg, DATE/TIMESTAMP columns as date/datetime, and
    # `vector` columns (embedding) as pgvector.Vector — none of which the ADK
    # tool-result JSON encoder can serialize.
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Vector):
        return value.to_list()
    return value


def sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make query result rows JSON-serializable for returning from an agent
    tool (Decimal -> float, date/datetime -> ISO string, Vector -> list)."""
    return [{key: _json_safe(value) for key, value in row.items()} for row in rows]
