from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_TEST = "apps/backend/tests/security/test_tenant_isolation_matrix.py"
PGTAP_TEST = "supabase/tests/rls_matrix_test.sql"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> int:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
    ).returncode


def _local_database_url() -> str:
    if (REPOSITORY_ROOT / "supabase/.temp/project-ref").exists():
        raise RuntimeError(
            "linked Supabase projects are forbidden for local test gates"
        )

    status = subprocess.run(
        ["pnpm", "supabase", "status", "-o", "json"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise RuntimeError("local Supabase database status is unavailable")
    try:
        status_payload = json.loads(status.stdout)
        if not isinstance(status_payload, dict):
            raise TypeError
        database_url = status_payload["DB_URL"]
        if not isinstance(database_url, str):
            raise TypeError
        parsed = urlsplit(database_url)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("local Supabase database status is invalid") from error
    if parsed.scheme != "postgresql" or parsed.hostname not in LOOPBACK_HOSTS:
        raise RuntimeError("tenant isolation tests require loopback PostgreSQL")
    return database_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-ready",
        action="store_true",
        help="reuse a database already reset by the aggregate security runner",
    )
    arguments = parser.parse_args()

    if not arguments.database_ready:
        reset_result = _run(["sh", "infrastructure/scripts/ensure_local_database.sh"])
        if reset_result != 0:
            return reset_result

    try:
        database_url = _local_database_url()
    except RuntimeError as error:
        print(f"run_tenant_isolation: {error}", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["TEST_DATABASE_URL"] = database_url.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )
    python_result = _run(
        ["uv", "run", "--all-packages", "pytest", MATRIX_TEST],
        environment=environment,
    )
    if python_result != 0:
        return python_result
    return _run(["pnpm", "supabase", "test", "db", "--local", PGTAP_TEST])


if __name__ == "__main__":
    raise SystemExit(main())
