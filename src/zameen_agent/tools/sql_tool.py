"""Read-only SQL tool for the agent: runs a single SELECT and returns rows.

Guardrails (defense in depth — no single layer should be relied on alone):
  1. Query-text checks here: must be exactly one statement, must start with
     SELECT/WITH, no write/DDL keywords, no stacked statements.
  2. `SET TRANSACTION READ ONLY` at the DB session level (db.get_connection).
  3. Recommended (see db/schema.sql): run as a Postgres role with SELECT-only
     grants, not the app's default role.
"""

from __future__ import annotations

import re

import psycopg

from zameen_agent.config import settings
from zameen_agent.db import get_connection, sanitize_rows

_WRITE_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "COPY", "CALL", "MERGE", "EXECUTE", "VACUUM",
    "REINDEX", "REFRESH", "LOCK", "SET", "RESET", "DO",
)

_LEADING_KEYWORD_RE = re.compile(r"^\s*(\w+)", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """Raised when a query fails the read-only single-statement guardrail."""


def _validate_select_only(query: str) -> str:
    stripped = query.strip()
    if not stripped:
        raise UnsafeQueryError("Empty query.")

    # Reject stacked statements: only one trailing semicolon (or none) allowed.
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        raise UnsafeQueryError("Only a single SQL statement is allowed.")

    leading_match = _LEADING_KEYWORD_RE.match(body)
    leading_keyword = leading_match.group(1).upper() if leading_match else ""
    if leading_keyword not in ("SELECT", "WITH"):
        raise UnsafeQueryError("Only SELECT (or SELECT-only WITH) statements are allowed.")

    tokens = {t.upper() for t in re.findall(r"[A-Za-z_]+", body)}
    forbidden = tokens & set(_WRITE_KEYWORDS)
    if forbidden:
        raise UnsafeQueryError(
            f"Query contains disallowed keyword(s): {', '.join(sorted(forbidden))}"
        )

    return body


def sql_query(query: str) -> list[dict] | dict[str, str]:
    """Run a single read-only SELECT statement against the listings database.

    Use this for exact filters and aggregates over the `listings` table —
    e.g. "how many listings in Lahore are for rent under 50,000 PKR/month",
    "average price per Marla in DHA Karachi", "count of 3-bed houses for
    sale". Prices are in PKR (price_pkr column); purpose is 'sale' or 'rent'.
    Prefer semantic_search instead for fuzzy/descriptive requests that aren't
    expressible as exact column filters.

    Only a single SELECT statement is permitted — no INSERT/UPDATE/DELETE/DDL
    and no multiple statements. A LIMIT is appended automatically if you
    don't include one, capped at a configurable max (see
    ZAMEEN_SQL_TOOL_MAX_ROWS, default 200).

    If the query is rejected by the guardrail, or Postgres rejects it (e.g. a
    typo'd column name), this returns `{"error": "<message>"}` instead of
    raising — so you can read the error and retry with a corrected query
    rather than the whole conversation failing.

    Args:
        query: A single PostgreSQL SELECT statement against the `listings`
            table (see db/schema.sql for the full column list).

    Returns:
        A list of result rows as dicts, or `{"error": "..."}` on failure.
    """
    try:
        validated = _validate_select_only(query)
    except UnsafeQueryError as exc:
        return {"error": str(exc)}

    if not _LIMIT_RE.search(validated):
        validated = f"{validated} LIMIT {settings.sql_tool_max_rows}"

    try:
        with get_connection(read_only=True) as conn:
            with conn.cursor() as cur:
                cur.execute(validated)
                return sanitize_rows(cur.fetchall())
    except psycopg.Error as exc:
        return {"error": str(exc).strip()}
