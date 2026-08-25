from __future__ import annotations

import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture(scope="session")
def local_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "TEST_DATABASE_URL is required; run integration tests through "
            "`make test-integration`"
        )

    parsed = urlsplit(database_url)
    if parsed.scheme != "postgresql+asyncpg" or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        pytest.fail("integration tests require the isolated local Supabase database")
    return database_url


@pytest_asyncio.fixture
async def database_engine(local_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(local_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(
    database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(database_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_foundation_tables(database_engine: AsyncEngine) -> AsyncIterator[None]:
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET TRUE"
            )
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE "
                "public.dead_letter_jobs, "
                "public.job_attempts, "
                "public.outbox_jobs, "
                "public.audit_events, "
                "public.platform_admins, "
                "public.tenants CASCADE"
            )
        )
    yield
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE "
                "public.dead_letter_jobs, "
                "public.job_attempts, "
                "public.outbox_jobs, "
                "public.audit_events, "
                "public.platform_admins, "
                "public.tenants CASCADE"
            )
        )
        await connection.execute(
            text(
                "GRANT agents_factory_app, agents_factory_admin TO CURRENT_USER "
                "WITH INHERIT FALSE, SET FALSE"
            )
        )
