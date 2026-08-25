from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_VALIDATORS = (
    REPOSITORY_ROOT / "infrastructure/scripts/verify_ci_workflow.sh",
    REPOSITORY_ROOT / "infrastructure/scripts/check_repository_security.sh",
)


def _run_validator(validator: Path, workflow: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(validator), str(workflow)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _desired_workflow() -> str:
    source = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text()
    if "      - run: make test-integration\n" not in source:
        source = source.replace(
            "      - run: make test-unit\n",
            "      - run: make test-unit\n      - run: make test-integration\n",
        )
    return source


@pytest.mark.parametrize("validator", WORKFLOW_VALIDATORS)
def test_workflow_validators_reject_missing_integration_gate(
    validator: Path,
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "missing-integration.yml"
    workflow.write_text(
        _desired_workflow().replace("      - run: make test-integration\n", "")
    )

    result = _run_validator(validator, workflow)

    assert result.returncode != 0
    assert "run commands must exactly match" in result.stderr


@pytest.mark.parametrize("validator", WORKFLOW_VALIDATORS)
def test_workflow_validators_reject_out_of_sequence_integration_gate(
    validator: Path,
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "out-of-sequence.yml"
    workflow.write_text(
        _desired_workflow().replace(
            "      - run: make test-unit\n      - run: make test-integration\n",
            "      - run: make test-integration\n      - run: make test-unit\n",
        )
    )

    result = _run_validator(validator, workflow)

    assert result.returncode != 0
    assert "run commands must exactly match" in result.stderr


def _run_policy_drift(
    migration: Path, policy: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(
                REPOSITORY_ROOT
                / "infrastructure/scripts/check_supabase_policy_drift.sh"
            ),
            str(migration),
            str(policy),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


FOUNDATION_TABLES = (
    "tenants",
    "platform_admins",
    "audit_events",
    "outbox_jobs",
    "job_attempts",
    "dead_letter_jobs",
)
POLICY_MUTATIONS = (
    "CrEaTe\n  PoLiCy extra_policy\nON public.{table}\n"
    "FOR SELECT TO agents_factory_app USING (true);",
    "AlTeR\n  PoLiCy existing_policy\nON public.{table}\nWITH CHECK (true);",
    "DrOp\n  PoLiCy existing_policy\nON public.{table};",
    'AlTeR\n  PoLiCy quoted_policy\nON "public"."{table}"\nUSING (true);',
    "AlTeR\n  PoLiCy unqualified_policy\nON {table}\nUSING (true);",
)


@pytest.mark.parametrize("table_name", FOUNDATION_TABLES)
@pytest.mark.parametrize("mutation", POLICY_MUTATIONS)
def test_policy_drift_rejects_authorization_mutation_outside_markers(
    table_name: str,
    mutation: str,
    tmp_path: Path,
) -> None:
    migration = tmp_path / "foundation.sql"
    policy = tmp_path / "tenant_isolation.sql"
    migration.write_text(
        (
            REPOSITORY_ROOT / "supabase/migrations/20260825132406_foundation.sql"
        ).read_text()
        + f"\n{mutation.format(table=table_name)}\n"
    )
    policy.write_text(
        (REPOSITORY_ROOT / "supabase/policies/tenant_isolation.sql").read_text()
    )

    result = _run_policy_drift(migration, policy)

    assert result.returncode != 0
    assert "outside canonical block" in result.stderr


def test_policy_drift_ignores_comments_strings_and_unrelated_identifiers(
    tmp_path: Path,
) -> None:
    migration = tmp_path / "foundation.sql"
    policy = tmp_path / "tenant_isolation.sql"
    migration.write_text(
        (
            REPOSITORY_ROOT / "supabase/migrations/20260825132406_foundation.sql"
        ).read_text()
        + "\n-- ALTER POLICY comment_only ON public.outbox_jobs;\n"
        "/* DROP POLICY block_comment ON public.audit_events; */\n"
        "select 'CREATE POLICY string_only ON public.tenants';\n"
        "select $body$ALTER POLICY dollar_string ON public.outbox_jobs;$body$;\n"
        "create policy unrelated_policy on public.audit_events_archive using (true);\n"
        "alter table public.outbox_jobs_archive add column policy_note text;\n"
        'create table "CREATE POLICY identifier_only ON public.tenants" (id int);\n'
    )
    policy.write_text(
        (REPOSITORY_ROOT / "supabase/policies/tenant_isolation.sql").read_text()
    )

    result = _run_policy_drift(migration, policy)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "prefix",
    (
        "select '\\';\n",
        "select harmless$tag$;\n",
    ),
)
def test_policy_drift_does_not_hide_executable_policy_after_identifier_or_string(
    prefix: str,
    tmp_path: Path,
) -> None:
    migration = tmp_path / "foundation.sql"
    policy = tmp_path / "tenant_isolation.sql"
    migration.write_text(
        (
            REPOSITORY_ROOT / "supabase/migrations/20260825132406_foundation.sql"
        ).read_text()
        + f"\n{prefix}ALTER POLICY bypass ON outbox_jobs USING (true);\n"
    )
    policy.write_text(
        (REPOSITORY_ROOT / "supabase/policies/tenant_isolation.sql").read_text()
    )

    result = _run_policy_drift(migration, policy)

    assert result.returncode != 0
    assert "outside canonical block" in result.stderr


def test_policy_drift_rejects_duplicate_marker_pair(tmp_path: Path) -> None:
    migration = tmp_path / "foundation.sql"
    policy = tmp_path / "tenant_isolation.sql"
    migration.write_text(
        (
            REPOSITORY_ROOT / "supabase/migrations/20260825132406_foundation.sql"
        ).read_text()
        + "\n-- BEGIN CANONICAL TENANT ISOLATION POLICIES\n"
        "-- END CANONICAL TENANT ISOLATION POLICIES\n"
    )
    policy.write_text(
        (REPOSITORY_ROOT / "supabase/policies/tenant_isolation.sql").read_text()
    )

    result = _run_policy_drift(migration, policy)

    assert result.returncode != 0
    assert "exactly one canonical marker pair" in result.stderr
