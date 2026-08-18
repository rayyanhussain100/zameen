"""Postgres connection helper.

Thin wrapper over psycopg (v3) — no ORM. Registers the pgvector adapter so
`vector` columns round-trip as Python lists of floats.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
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
