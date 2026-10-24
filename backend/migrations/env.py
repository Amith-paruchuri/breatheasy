"""Alembic environment: async engine, URL from app settings (DATABASE_URL)."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.db import Base

target_metadata = Base.metadata


def _url() -> str:
    return context.config.attributes.get("database_url") or Settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    conn = context.config.attributes.get("connection")
    if conn is not None:
        _do_run(conn)
        return
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif context.config.attributes.get("connection") is not None:
    _do_run(context.config.attributes["connection"])
else:
    asyncio.run(run_migrations_online())
