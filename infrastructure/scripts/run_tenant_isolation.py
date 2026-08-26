from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from local_database_url import (
    LocalDatabaseUrlError,
    normalize_status_database_url,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_TEST = "apps/backend/tests/security/test_tenant_isolation_matrix.py"
SECRET_DATABASE_TEST = "apps/backend/tests/security/test_secret_tenant_isolation.py"
PGTAP_TEST = "supabase/tests/rls_matrix_test.sql"
EXPECTED_DATABASE = "postgres"


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> int:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
    ).returncode


def _expected_local_port() -> int:
    try:
        with (REPOSITORY_ROOT / "supabase/config.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
        port = config["db"]["port"]
    except (KeyError, OSError, TypeError, tomllib.TOMLDecodeError) as error:
        raise RuntimeError("local Supabase database port is unavailable") from error
    if not isinstance(port, int):
        raise RuntimeError("local Supabase database port is invalid")
    return port


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
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("local Supabase database status is invalid") from error
    try:
        return normalize_status_database_url(
            database_url,
            expected_port=_expected_local_port(),
            expected_database=EXPECTED_DATABASE,
        )
    except LocalDatabaseUrlError as error:
        raise RuntimeError("local Supabase database target is unsafe") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    reset_result = _run(["sh", "infrastructure/scripts/ensure_local_database.sh"])
    if reset_result != 0:
        return reset_result

    try:
        database_url = _local_database_url()
    except RuntimeError as error:
        print(f"run_tenant_isolation: {error}", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["TEST_DATABASE_URL"] = database_url
    environment["APP_MASTER_KEY"] = (
        base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    )
    python_result = _run(
        [
            "uv",
            "run",
            "--all-packages",
            "pytest",
            MATRIX_TEST,
            SECRET_DATABASE_TEST,
        ],
        environment=environment,
    )
    if python_result != 0:
        return python_result
    return _run(["pnpm", "supabase", "test", "db", "--local", PGTAP_TEST])


if __name__ == "__main__":
    raise SystemExit(main())
