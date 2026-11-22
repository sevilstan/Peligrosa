"""Shared test helpers.

Database tests need a DEDICATED, disposable PostgreSQL database. They create
and drop every table, so they must never run against your development data.
Set TEST_DATABASE_URL to a database whose name ends with "_test", e.g.:

    postgresql+asyncpg://user:password@localhost:5432/peligrosa_test

Create it once with:  CREATE DATABASE peligrosa_test;
Without TEST_DATABASE_URL the database tests are skipped.
"""

import asyncio
import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")

    if not url:
        pytest.skip("TEST_DATABASE_URL is not set (database tests need a *_test database).")

    database_name = make_url(url).database or ""

    if not database_name.endswith("_test"):
        # Fail loudly: silently running drop_all on the wrong database is worse.
        pytest.fail(
            "TEST_DATABASE_URL must point to a database whose name ends with "
            f"'_test' (got '{database_name}'). These tests drop all tables."
        )

    return url


@pytest.fixture
def run_db():
    """Run an async scenario(maker) against a fresh, empty test database."""
    url = _test_database_url()

    def runner(scenario):
        async def main():
            engine = create_async_engine(url)

            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)

            maker = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )

            try:
                await scenario(maker)
            finally:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.drop_all)
                await engine.dispose()

        asyncio.run(main())

    return runner
