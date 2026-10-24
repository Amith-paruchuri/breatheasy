"""Apply database migrations.

Runs at startup (RUN_MIGRATIONS_ON_STARTUP=true) and as `python -m app.migrate`.
On Postgres a session advisory lock makes concurrent Cloud Run instances wait
for each other instead of racing the same migration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("breatheasy.migrate")

_LOCK_KEY = 74_210_513  # arbitrary, constant across deploys
_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(connection) -> Config:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        postgres = conn.dialect.name == "postgresql"
        if postgres:
            await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        try:
            await conn.run_sync(lambda sync_conn: command.upgrade(_alembic_config(sync_conn), "head"))
            await conn.commit()
        finally:
            if postgres:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                await conn.commit()
    log.info("database migrations applied")


async def _main() -> None:
    from .config import get_settings
    from .db import make_engine

    engine = make_engine(get_settings().database_url)
    try:
        await run_migrations(engine)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
