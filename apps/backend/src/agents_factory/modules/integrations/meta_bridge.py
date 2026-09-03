from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.integrations.models import (
    ConnectionSummary,
    ConnectorHealth,
)
from agents_factory.modules.whatsapp.account_service import (
    WhatsAppAccountService,
    WhatsAppAccountSummary,
)
from agents_factory.modules.whatsapp.signup_service import REQUIRED_META_SCOPES


class MetaConnectionBridge:
    """Project existing Meta accounts, without duplicating their encrypted credentials."""

    def __init__(self, accounts: WhatsAppAccountService) -> None:
        self._accounts = accounts

    async def list(self, context: TenantContext) -> tuple[ConnectionSummary, ...]:
        return tuple(
            _summary(account, context.tenant_id)
            for account in await self._accounts.list_summaries(context=context)
        )

    async def check_health(
        self, context: TenantContext, connection_id: UUID
    ) -> ConnectionSummary:
        return _summary(
            await self._accounts.check_health(
                context=context, account_id=connection_id, checked_at=datetime.now(UTC)
            ),
            context.tenant_id,
        )

    async def revoke(
        self, context: TenantContext, connection_id: UUID
    ) -> ConnectionSummary:
        return _summary(
            await self._accounts.revoke(
                context=context, account_id=connection_id, revoked_at=datetime.now(UTC)
            ),
            context.tenant_id,
        )


def _summary(account: WhatsAppAccountSummary, tenant_id: UUID) -> ConnectionSummary:
    return ConnectionSummary(
        id=account.id,
        tenant_id=tenant_id,
        connector_name="meta_whatsapp",
        auth_kind="META_EMBEDDED",
        status=(
            "REVOKED"
            if account.status != "active"
            else "REAUTH_REQUIRED"
            if account.health_status == "REAUTH_REQUIRED"
            else "CONNECTED"
        ),
        requested_scopes=tuple(sorted(REQUIRED_META_SCOPES)),
        granted_scopes=account.granted_scopes,
        expires_at=account.token_expires_at,
        health=ConnectorHealth(
            status=account.health_status, checked_at=account.last_health_checked_at
        ),
    )
