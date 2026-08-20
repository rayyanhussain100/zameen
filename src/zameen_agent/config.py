"""Environment-driven settings, loaded once from .env.

Deliberately a plain dataclass over os.environ rather than pydantic-settings —
the config surface here is small and doesn't need a validation framework.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://zameen:zameen@localhost:5432/zameen"
        )
    )

    google_api_key: str = field(default_factory=lambda: os.environ.get("GOOGLE_API_KEY", ""))
    agent_model: str = field(
        default_factory=lambda: os.environ.get("ZAMEEN_AGENT_MODEL", "gemini-2.0-flash")
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("ZAMEEN_EMBEDDING_MODEL", "gemini-embedding-001")
    )
    embedding_dim: int = 768

    min_delay_seconds: float = field(
        default_factory=lambda: _float_env("ZAMEEN_MIN_DELAY_SECONDS", 3.0)
    )
    jitter_seconds: float = field(
        default_factory=lambda: _float_env("ZAMEEN_JITTER_SECONDS", 2.0)
    )
    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "ZAMEEN_USER_AGENT", "ZameenAgentBot/0.1 (+contact: you@example.com)"
        )
    )
    max_retries: int = field(default_factory=lambda: _int_env("ZAMEEN_MAX_RETRIES", 5))

    sql_tool_max_rows: int = field(
        default_factory=lambda: _int_env("ZAMEEN_SQL_TOOL_MAX_ROWS", 200)
    )


settings = Settings()
