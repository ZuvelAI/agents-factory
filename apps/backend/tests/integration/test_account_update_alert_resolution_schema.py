from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine


RESOLUTIONS = "agents_factory_private.whatsapp_account_update_alert_resolutions"


@pytest.mark.asyncio
async def test_resolution_schema_restricts_roles(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid = "
                    "'agents_factory_private.whatsapp_account_update_alert_resolutions'::regclass"
                )
            )
        ).one()
        assert row == (True, True)

        public_grants = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_class c, LATERAL aclexplode(c.relacl) acl "
                "WHERE c.oid = "
                "'agents_factory_private.whatsapp_account_update_alert_resolutions'::regclass "
                "AND acl.grantee = 0"
            )
        )
        assert public_grants == 0

        for role in ("anon", "authenticated", "service_role", "agents_factory_app"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                allowed = await connection.scalar(
                    text("SELECT has_table_privilege(:role, :table_name, :privilege)"),
                    {"role": role, "table_name": RESOLUTIONS, "privilege": privilege},
                )
                assert allowed is False, (role, privilege)

        for privilege in ("SELECT", "INSERT"):
            assert (
                await connection.scalar(
                    text(
                        "SELECT has_table_privilege('agents_factory_admin', :table_name, :privilege)"
                    ),
                    {"table_name": RESOLUTIONS, "privilege": privilege},
                )
                is True
            )
        for privilege in ("UPDATE", "DELETE"):
            assert (
                await connection.scalar(
                    text(
                        "SELECT has_table_privilege('agents_factory_admin', :table_name, :privilege)"
                    ),
                    {"table_name": RESOLUTIONS, "privilege": privilege},
                )
                is False
            )


@pytest.mark.asyncio
async def test_resolution_requires_existing_alert_and_single_note(
    database_engine: AsyncEngine,
) -> None:
    alert_id = uuid4()
    resolver_id = uuid4()

    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO agents_factory_private.whatsapp_account_update_alerts "
                "(id, event_fingerprint, waba_id, event, occurred_at, reason) "
                "VALUES (:id, :fingerprint, 'waba-test', 'ACCOUNT_OFFBOARDED', "
                ":occurred_at, 'unsupported_event')"
            ),
            {"id": alert_id, "fingerprint": "a" * 64, "occurred_at": datetime.now(UTC)},
        )
        await connection.execute(
            text(
                "INSERT INTO agents_factory_private.whatsapp_account_update_alert_resolutions "
                "(alert_id, resolved_by, resolution_note) "
                "VALUES (:alert_id, :resolved_by, 'Checked in Meta')"
            ),
            {"alert_id": alert_id, "resolved_by": resolver_id},
        )

    with pytest.raises(IntegrityError):
        async with database_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO agents_factory_private.whatsapp_account_update_alert_resolutions "
                    "(alert_id, resolved_by, resolution_note) "
                    "VALUES (:alert_id, :resolved_by, 'Second resolution')"
                ),
                {"alert_id": alert_id, "resolved_by": resolver_id},
            )

    with pytest.raises(IntegrityError):
        async with database_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO agents_factory_private.whatsapp_account_update_alert_resolutions "
                    "(alert_id, resolved_by, resolution_note) "
                    "VALUES (:alert_id, :resolved_by, 'Missing alert')"
                ),
                {"alert_id": uuid4(), "resolved_by": resolver_id},
            )

    for note in (
        " ",
        "\t",
        "\n",
        "\u00a0",
        "\u2003",
        "\tleading",
        "trailing\n",
        " leading space",
        "x" * 501,
    ):
        invalid_alert_id = uuid4()
        async with database_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO agents_factory_private.whatsapp_account_update_alerts "
                    "(id, event_fingerprint, waba_id, event, occurred_at, reason) "
                    "VALUES (:id, :fingerprint, 'waba-test', 'ACCOUNT_OFFBOARDED', "
                    ":occurred_at, 'unsupported_event')"
                ),
                {
                    "id": invalid_alert_id,
                    "fingerprint": uuid4().hex * 2,
                    "occurred_at": datetime.now(UTC),
                },
            )
        with pytest.raises(IntegrityError):
            async with database_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO agents_factory_private.whatsapp_account_update_alert_resolutions "
                        "(alert_id, resolved_by, resolution_note) "
                        "VALUES (:alert_id, :resolved_by, :note)"
                    ),
                    {
                        "alert_id": invalid_alert_id,
                        "resolved_by": resolver_id,
                        "note": note,
                    },
                )

    async with database_engine.connect() as connection:
        assert (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM agents_factory_private.whatsapp_account_update_alert_resolutions"
                )
            )
            == 1
        )
