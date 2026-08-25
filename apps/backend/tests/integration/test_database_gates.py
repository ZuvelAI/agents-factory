from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.asyncio
async def test_database_gate_removes_stale_schema_state(
    database_engine: AsyncEngine,
) -> None:
    async with database_engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE public.task3_review_stale_marker()")
        )

    reset = subprocess.run(
        [str(REPOSITORY_ROOT / "infrastructure/scripts/ensure_local_database.sh")],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert reset.returncode == 0, reset.stderr
    assert "postgresql://" not in reset.stdout + reset.stderr
    await database_engine.dispose()
    async with database_engine.connect() as connection:
        marker = await connection.scalar(
            text("SELECT to_regclass('public.task3_review_stale_marker')")
        )
    assert marker is None
