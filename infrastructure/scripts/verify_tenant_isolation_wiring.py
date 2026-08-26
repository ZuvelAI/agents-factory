from __future__ import annotations

import sys
from pathlib import Path


RUNNER_INVOCATION = (
    "uv run --all-packages python infrastructure/scripts/run_tenant_isolation.py"
)
SEPARATE_RESET = "sh infrastructure/scripts/ensure_local_database.sh"


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "verify_tenant_isolation_wiring: one aggregate path is required",
            file=sys.stderr,
        )
        return 2

    aggregate_path = Path(sys.argv[1])
    try:
        executable_lines = [
            line.strip()
            for line in aggregate_path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError as error:
        print(
            f"verify_tenant_isolation_wiring: aggregate is unreadable: {error}",
            file=sys.stderr,
        )
        return 1

    if executable_lines.count(RUNNER_INVOCATION) != 1:
        print(
            "verify_tenant_isolation_wiring: exactly one tenant isolation "
            "runner invocation is required",
            file=sys.stderr,
        )
        return 1
    if SEPARATE_RESET in executable_lines or any(
        "--database-ready" in line for line in executable_lines
    ):
        print(
            "verify_tenant_isolation_wiring: the focused runner must own the "
            "single reset",
            file=sys.stderr,
        )
        return 1

    print("verify_tenant_isolation_wiring: pre-matrix wiring contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
