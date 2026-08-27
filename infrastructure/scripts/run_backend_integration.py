from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit


def main() -> int:
    try:
        status = subprocess.run(
            ["pnpm", "supabase", "status", "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        database_url = json.loads(status.stdout)["DB_URL"]
    except (KeyError, json.JSONDecodeError, subprocess.CalledProcessError):
        print(
            "run_backend_integration: local database status is unavailable",
            file=sys.stderr,
        )
        return 1

    redis = subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "redis"],
        check=False,
    )
    if redis.returncode != 0:
        print(
            "run_backend_integration: local Redis failed to start",
            file=sys.stderr,
        )
        return 1

    parsed = urlsplit(database_url)
    if parsed.scheme != "postgresql" or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        print(
            "run_backend_integration: refusing a non-local database",
            file=sys.stderr,
        )
        return 1

    environment = os.environ.copy()
    environment["TEST_DATABASE_URL"] = database_url.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )
    environment["TEST_REDIS_URL"] = "redis://127.0.0.1:6379/15"
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--all-packages",
            "pytest",
            "apps/backend/tests/integration",
        ],
        env=environment,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
