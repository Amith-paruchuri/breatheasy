import os
import tempfile

# Tests never touch the network or a real database.
_tmp = tempfile.mkdtemp(prefix="breatheasy-test-")
os.environ["PROVIDER"] = "mock"
# Set TEST_DATABASE_URL=postgresql+asyncpg://... to run the suite against Postgres.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["STATIC_DIR"] = os.path.join(_tmp, "no-static")
os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
os.environ["SESSION_SECRET"] = "x" * 40
os.environ.pop("ENV", None)

if os.environ.get("TEST_DATABASE_URL"):
    # A Postgres test database persists between runs: start every run from an empty schema.
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _reset() -> None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(_reset())
