from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "infrastructure/scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from local_database_url import (  # noqa: E402
    LocalDatabaseUrlError,
    normalize_status_database_url,
    validate_test_database_url,
)


EXPECTED_PORT = 54322
EXPECTED_DATABASE = "postgres"


@pytest.mark.parametrize(
    ("raw_url", "expected_host"),
    (
        (
            "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
            "127.0.0.1",
        ),
        (
            "postgresql://postgres:p%40ss@localhost:54322/postgres",
            "localhost",
        ),
        (
            "postgresql://postgres:postgres@[::1]:54322/postgres",
            "::1",
        ),
    ),
)
def test_status_dsn_is_normalized_to_one_effective_loopback_target(
    raw_url: str,
    expected_host: str,
) -> None:
    normalized = normalize_status_database_url(
        raw_url,
        expected_port=EXPECTED_PORT,
        expected_database=EXPECTED_DATABASE,
    )

    url = make_url(normalized)
    assert url.drivername == "postgresql+asyncpg"
    assert url.query == {}
    assert url.translate_connect_args() == {
        "host": expected_host,
        "database": EXPECTED_DATABASE,
        "username": "postgres",
        "password": "p@ss" if "p%40ss" in raw_url else "postgres",
        "port": EXPECTED_PORT,
    }


@pytest.mark.parametrize(
    "raw_url",
    (
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres?host=evil.example&port=5432",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres?host=evil.example&host=127.0.0.1",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres?host=%2Fvar%2Frun%2Fpostgresql",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres?application_name=task5",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres#other",
        "postgresql://postgres:postgres@127.0.0.1:54322,evil.example:5432/postgres",
        "postgresql://postgres:postgres@127.0.0.1,evil.example:5432/postgres",
        "postgresql://postgres:postgres@@127.0.0.1:54322/postgres",
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        "postgresql://postgres:postgres@127.0.0.1:54322/other",
        "postgresql://postgres:postgres@127.0.0.1:54322//postgres",
        "postgresql://postgres:postgres@127.0.0.1.evil:54322/postgres",
        "postgresql://postgres:postgres@%2Fvar%2Frun%2Fpostgresql:54322/postgres",
        "postgresql:///postgres",
    ),
)
def test_status_dsn_rejects_redirects_and_ambiguous_authorities(
    raw_url: str,
) -> None:
    with pytest.raises(LocalDatabaseUrlError):
        normalize_status_database_url(
            raw_url,
            expected_port=EXPECTED_PORT,
            expected_database=EXPECTED_DATABASE,
        )


def test_test_dsn_is_revalidated_before_sqlalchemy_can_connect() -> None:
    normalized = validate_test_database_url(
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres",
        expected_port=EXPECTED_PORT,
        expected_database=EXPECTED_DATABASE,
    )

    assert normalized == (
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
    )
    with pytest.raises(LocalDatabaseUrlError):
        validate_test_database_url(
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/"
            "postgres?host=evil.example",
            expected_port=EXPECTED_PORT,
            expected_database=EXPECTED_DATABASE,
        )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_runner_owns_exactly_one_reset_and_has_no_bypass_flag(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "sh",
        '#!/bin/sh\nprintf "sh %s\\n" "$*" >> "$TASK5_COMMAND_LOG"\nexit 0\n',
    )
    _write_executable(
        fake_bin / "uv",
        '#!/bin/sh\nprintf "uv %s\\n" "$*" >> "$TASK5_COMMAND_LOG"\nexit 0\n',
    )
    _write_executable(
        fake_bin / "pnpm",
        "#!/bin/sh\n"
        'printf "pnpm %s\\n" "$*" >> "$TASK5_COMMAND_LOG"\n'
        'if test "$1 $2 $3 $4" = "supabase status -o json"; then\n'
        "  printf '%s\\n' "
        '\'{"DB_URL":"postgresql://postgres:postgres@127.0.0.1:54322/postgres"}\'\n'
        "fi\n"
        "exit 0\n",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TASK5_COMMAND_LOG": str(command_log),
        }
    )
    runner = SCRIPTS_DIRECTORY / "run_tenant_isolation.py"

    result = subprocess.run(
        [sys.executable, str(runner)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    commands = command_log.read_text().splitlines()
    command_log.write_text("")
    bypass = subprocess.run(
        [sys.executable, str(runner), "--database-ready"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert commands == [
        "sh infrastructure/scripts/ensure_local_database.sh",
        "pnpm supabase status -o json",
        "uv run --all-packages pytest "
        "apps/backend/tests/security/test_tenant_isolation_matrix.py "
        "apps/backend/tests/security/test_secret_tenant_isolation.py",
        "pnpm supabase test db --local supabase/tests/rls_matrix_test.sql",
    ]
    assert bypass.returncode == 2
    assert "unrecognized arguments: --database-ready" in bypass.stderr
    assert command_log.read_text() == ""


def test_pre_matrix_wiring_gate_rejects_removed_runner_invocation(
    tmp_path: Path,
) -> None:
    aggregate = (
        REPOSITORY_ROOT / "infrastructure/scripts/check_repository_security.sh"
    ).read_text()
    invocation = (
        "uv run --all-packages python infrastructure/scripts/run_tenant_isolation.py"
    )
    valid = tmp_path / "valid-security.sh"
    mutated = tmp_path / "missing-matrix-security.sh"
    valid.write_text(aggregate)
    mutated.write_text(aggregate.replace(invocation, "true", 1))
    verifier = SCRIPTS_DIRECTORY / "verify_tenant_isolation_wiring.py"

    valid_result = subprocess.run(
        [sys.executable, str(verifier), str(valid)],
        capture_output=True,
        text=True,
        check=False,
    )
    mutated_result = subprocess.run(
        [sys.executable, str(verifier), str(mutated)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert valid_result.returncode == 0, valid_result.stderr
    assert mutated_result.returncode != 0
    assert "exactly one tenant isolation runner invocation" in mutated_result.stderr
