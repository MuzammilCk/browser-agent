"""PostgreSQL schema migration and initialization helper — Phase 8."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


async def apply_schema(connection_or_pool: Any) -> None:
    """Read schema.sql and apply to PostgreSQL database."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    if hasattr(connection_or_pool, "execute"):
        await connection_or_pool.execute(sql)
    elif hasattr(connection_or_pool, "acquire"):
        async with connection_or_pool.acquire() as conn:
            await conn.execute(sql)
    else:
        raise TypeError(f"Unsupported connection object: {type(connection_or_pool)}")
