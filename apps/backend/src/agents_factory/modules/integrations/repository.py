from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.integrations.models import (
    ConnectorHealth,
    IntegrationConnection,
    OAuthState,
)
from agents_factory.modules.secrets.contracts import SecretRef


class IntegrationRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context

    async def get(
        self, connection_id: UUID, *, lock: bool = False
    ) -> IntegrationConnection | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        suffix = " FOR UPDATE" if lock else ""
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.integration_connections "
                        "WHERE tenant_id = :tenant_id AND id = :id" + suffix
                    ),
                    {"tenant_id": self.context.tenant_id, "id": connection_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _connection(row)

    async def list(self) -> tuple[IntegrationConnection, ...]:
        await set_tenant_context(self.session, self.context.tenant_id)
        rows = (
            await self.session.execute(
                text(
                    "SELECT * FROM public.integration_connections "
                    "WHERE tenant_id = :tenant_id ORDER BY created_at, id"
                ),
                {"tenant_id": self.context.tenant_id},
            )
        ).mappings()
        return tuple(_connection(row) for row in rows)

    async def insert(self, connection: IntegrationConnection) -> None:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(
            text(
                "INSERT INTO public.integration_connections "
                "(id, tenant_id, connector_name, auth_kind, requested_scopes) "
                "VALUES (:id, :tenant_id, :connector_name, :auth_kind, :requested_scopes)"
            ),
            {
                "id": connection.id,
                "tenant_id": self.context.tenant_id,
                "connector_name": connection.connector_name,
                "auth_kind": connection.auth_kind,
                "requested_scopes": list(connection.requested_scopes),
            },
        )

    async def save(self, connection: IntegrationConnection) -> None:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(
            text(
                "UPDATE public.integration_connections SET status = :status, "
                "credential_secret_id = :credential_id, "
                "requested_scopes = :requested_scopes, granted_scopes = :granted_scopes, "
                "authorization_version = :version, expires_at = :expires_at, "
                "health_status = :health_status, last_health_checked_at = :checked_at, "
                "last_error_code = :error_code, updated_at = now() "
                "WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {
                "tenant_id": self.context.tenant_id,
                "id": connection.id,
                "status": connection.status,
                "credential_id": (
                    connection.credential_ref.id if connection.credential_ref else None
                ),
                "requested_scopes": list(connection.requested_scopes),
                "granted_scopes": list(connection.granted_scopes),
                "version": connection.authorization_version,
                "expires_at": connection.expires_at,
                "health_status": connection.health.status,
                "checked_at": connection.health.checked_at,
                "error_code": connection.health.error_code,
            },
        )

    async def insert_state(self, state: OAuthState) -> None:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(
            text(
                "INSERT INTO agents_factory_private.integration_oauth_states "
                "(state_digest, tenant_id, connection_id, admin_user_id, admin_session_id, "
                "authorization_version, verifier_secret_id, code_challenge, expires_at) "
                "VALUES (:digest, :tenant_id, :connection_id, :user_id, :session_id, "
                ":version, :verifier_id, :challenge, :expires_at)"
            ),
            {
                "digest": state.state_digest,
                "tenant_id": self.context.tenant_id,
                "connection_id": state.connection_id,
                "user_id": state.admin_user_id,
                "session_id": state.admin_session_id,
                "version": state.authorization_version,
                "verifier_id": state.verifier_ref.id,
                "challenge": state.code_challenge,
                "expires_at": state.expires_at,
            },
        )

    async def consume_state(
        self, *, digest: str, admin_session_id: UUID, now: datetime
    ) -> OAuthState | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        row = (
            (
                await self.session.execute(
                    text(
                        "UPDATE agents_factory_private.integration_oauth_states "
                        "SET consumed_at = :now WHERE state_digest = :digest "
                        "AND tenant_id = :tenant_id AND admin_user_id = :user_id "
                        "AND admin_session_id = :session_id AND consumed_at IS NULL "
                        "AND expires_at > :now AND verifier_secret_id IS NOT NULL RETURNING *"
                    ),
                    {
                        "digest": digest,
                        "tenant_id": self.context.tenant_id,
                        "user_id": self.context.actor_id,
                        "session_id": admin_session_id,
                        "now": now,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return OAuthState(
            state_digest=row["state_digest"],
            tenant_id=row["tenant_id"],
            connection_id=row["connection_id"],
            admin_user_id=row["admin_user_id"],
            admin_session_id=row["admin_session_id"],
            authorization_version=row["authorization_version"],
            verifier_ref=SecretRef(row["verifier_secret_id"]),
            code_challenge=row["code_challenge"],
            expires_at=row["expires_at"],
        )

    async def detach_verifier(self, digest: str) -> None:
        await self.session.execute(
            text(
                "UPDATE agents_factory_private.integration_oauth_states "
                "SET verifier_secret_id = NULL WHERE state_digest = :digest "
                "AND tenant_id = :tenant_id AND consumed_at IS NOT NULL"
            ),
            {"digest": digest, "tenant_id": self.context.tenant_id},
        )


def _connection(row: RowMapping) -> IntegrationConnection:
    return IntegrationConnection(
        id=row["id"],
        tenant_id=row["tenant_id"],
        connector_name=row["connector_name"],
        auth_kind=row["auth_kind"],
        status=row["status"],
        credential_ref=(
            SecretRef(row["credential_secret_id"])
            if row["credential_secret_id"]
            else None
        ),
        requested_scopes=tuple(row["requested_scopes"]),
        granted_scopes=tuple(row["granted_scopes"]),
        authorization_version=row["authorization_version"],
        expires_at=row["expires_at"],
        health=ConnectorHealth(
            status=row["health_status"],
            checked_at=row["last_health_checked_at"],
            error_code=row["last_error_code"],
        ),
    )
