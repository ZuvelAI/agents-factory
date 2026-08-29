from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CORE_ROOTS = (
    ROOT / "apps/backend/src",
    ROOT / "apps/control-plane/app",
    ROOT / "apps/control-plane/components",
    ROOT / "apps/control-plane/lib",
)
TENANT_CONDITIONAL = re.compile(r"\bif\s+[^\n]*\btenant_id\s*==")
LITERAL_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


def test_core_contains_no_customer_uuid_or_tenant_id_conditionals() -> None:
    violations: list[str] = []
    for root in CORE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            source = path.read_text(encoding="utf-8")
            if TENANT_CONDITIONAL.search(source) or LITERAL_UUID.search(source):
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []
