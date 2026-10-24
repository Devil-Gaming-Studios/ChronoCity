from __future__ import annotations

from typing import Any, Optional

import asyncpg

from ..config import settings

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Lazily create the asyncpg pool. Never required in BUS=memory demo mode."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def execute(sql: str, *args: Any) -> str:
    pool = await get_pool()
    return await pool.execute(sql, *args)


async def fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(sql, *args)


async def init_schema() -> None:
    """Apply schema.sql. Safe to call repeatedly."""
    from pathlib import Path

    sql_path = Path(__file__).with_name("schema.sql")
    sql = sql_path.read_text(encoding="utf-8")
    pool = await get_pool()
    await pool.execute(sql)
