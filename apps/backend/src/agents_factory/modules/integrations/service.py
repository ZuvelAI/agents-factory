from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.integrations.contracts import (
    Connector,
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.health import provider_failure_health
from agents_factory.modules.integrations.models import (
    ConnectionSummary,
    ConnectorHealth,
    IntegrationConnection,
    IntegrationError,
    OAuthState,
)
from agents_factory.modules.integrations.oauth import (
    PKCE_PURPOSE,
    AuthorizationGrant,
    OAuthStart,
    ProviderRegistry,
    new_oauth_proof,
    pkce_challenge,
    state_digest,
)
from agents_factory.modules.integrations.repository import IntegrationRepository
from agents_factory.modules.secrets.contracts import KeyEncryptionProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.secrets.repository import SecretVault


class IntegrationService:
    """Backend lifecycle; owns durable transaction boundaries, never returns secrets."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        key_provider: KeyEncryptionProvider,
        providers: ProviderRegistry,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._key_provider = key_provider
        self._providers = providers
        self._now = now or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def _transaction(
        self, context: TenantContext, *, backend_execution: bool = False
    ) -> AsyncIterator[tuple[IntegrationRepository, SecretVault]]:
        if context.actor_id is None or not (
            context.actor_type == "platform_admin"
            or (backend_execution and context.actor_type == "system")
        ):
            raise IntegrationError("platform_admin_required", status=403)
        async with self._sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            yield (
                IntegrationRepository(session, context),
                SecretVault.for_session(session, key_provider=self._key_provider),
            )

    async def list(self, *, context: TenantContext) -> tuple[ConnectionSummary, ...]:
        async with self._transaction(context) as (repository, _vault):
            return tuple(item.summary() for item in await repository.list())

    async def execute_connector(
        self,
        *,
        context: TenantContext,
        connection_id: UUID,
        connector_name: str,
        request: ConnectorRequest,
        build: Callable[[ResolvedSecret], Connector],
    ) -> ConnectorResult:
        """Backend-only credential lease; serialized with refresh and revocation.

        `build` is code-owned composition, never a user/model-supplied callback.
        Customer-facing invocations must pass existing Action/Capability gates.
        """
        if context.tenant_id != request.tenant_id:
            return ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="tenant_mismatch",
            )
        async with self._transaction(context, backend_execution=True) as (
            repository,
            vault,
        ):
            connection = await _get(repository, connection_id)
            if (
                connection.connector_name != connector_name
                or connection.status != "CONNECTED"
            ):
                return ConnectorResult(
                    operation=request.operation,
                    status="REJECTED",
                    error_code="integration_not_connected",
                )
            credential = await _load_credential(vault, context, connection)
            if (
                connection.expires_at is not None
                and connection.expires_at <= self._now() + timedelta(seconds=60)
            ):
                try:
                    grant = await self._providers.get(connector_name).refresh(
                        credential
                    )
                    _validate_grant(grant, connection, now=self._now())
                except Exception as error:
                    health = provider_failure_health(error, now=self._now())
                    connection = replace(
                        connection,
                        health=health,
                        status="REAUTH_REQUIRED"
                        if health.status == "REAUTH_REQUIRED"
                        else connection.status,
                    )
                    await repository.save(connection)
                    await _audit(repository, connection, "refresh_failed")
                    return ConnectorResult(
                        operation=request.operation,
                        status="FAILED",
                        error_code=health.error_code,
                    )
                connection = await self._replace_credential(
                    repository, vault, connection, grant
                )
                credential = grant.credential
            result = await build(credential).execute(request)
            if result.error_code in {"authorization_revoked", "credentials_expired"}:
                connection = replace(
                    connection,
                    status="REAUTH_REQUIRED",
                    health=ConnectorHealth(
                        status="REAUTH_REQUIRED",
                        checked_at=self._now(),
                        error_code=result.error_code,
                    ),
                )
                await repository.save(connection)
            await AuditService(repository.session).record(
                context=context,
                event_type="integration.operation",
                entity_type="integration_connection",
                entity_id=connection.id,
                payload={
                    "connector": connector_name,
                    "operation": request.operation,
                    "binding_id": str(request.binding_id),
                    "status": result.status,
                    "error_code": result.error_code,
                },
            )
            return result

    async def start_oauth(
        self,
        *,
        context: TenantContext,
        admin_session_id: UUID,
        connector_name: str,
        scopes: tuple[str, ...],
        connection_id: UUID | None = None,
    ) -> OAuthStart:
        configuration = self._providers.get(connector_name).oauth
        if configuration is None:
            raise IntegrationError("integration_oauth_unsupported", status=400)
        requested = tuple(sorted(set(scopes)))
        state_value, verifier, challenge = new_oauth_proof()
        authorization_url = configuration.authorize_url(
            state=state_value, code_challenge=challenge, scopes=requested
        )
        expires_at = self._now() + timedelta(minutes=10)
        async with self._transaction(context) as (repository, vault):
            if connection_id is None:
                connection = IntegrationConnection(
                    id=new_uuid7(),
                    tenant_id=context.tenant_id,
                    connector_name=connector_name,
                    auth_kind="OAUTH2",
                )
                await repository.insert(connection)
            else:
                connection = await _get(repository, connection_id)
                if (
                    connection.connector_name != connector_name
                    or connection.auth_kind != "OAUTH2"
                    or connection.status == "REVOKING"
                ):
                    raise IntegrationError("integration_reconnect_invalid")
            connection = replace(
                connection,
                status="PENDING",
                requested_scopes=requested,
                authorization_version=connection.authorization_version + 1,
                health=ConnectorHealth(),
            )
            await repository.save(connection)
            digest = state_digest(state_value)
            verifier_ref = await vault.store(
                context=context,
                purpose=PKCE_PURPOSE,
                record_context=f"integration_oauth_state:{digest}",
                plaintext=verifier.reveal(),
            )
            assert context.actor_id is not None
            await repository.insert_state(
                OAuthState(
                    state_digest=digest,
                    tenant_id=context.tenant_id,
                    connection_id=connection.id,
                    admin_user_id=context.actor_id,
                    admin_session_id=admin_session_id,
                    authorization_version=connection.authorization_version,
                    verifier_ref=verifier_ref,
                    code_challenge=challenge,
                    expires_at=expires_at,
                )
            )
            await _audit(repository, connection, "authorization_started")
        return OAuthStart(
            connection_id=connection.id,
            authorization_url=authorization_url,
            requested_scopes=requested,
            expires_at=expires_at,
        )

    async def complete_oauth(
        self,
        *,
        context: TenantContext,
        admin_session_id: UUID,
        state: str,
        code: ResolvedSecret,
    ) -> ConnectionSummary:
        # Consume independently: a provider/DB failure must not resurrect this state.
        async with self._transaction(context) as (repository, _vault):
            claimed = await repository.consume_state(
                digest=state_digest(state),
                admin_session_id=admin_session_id,
                now=self._now(),
            )
            if claimed is None:
                await AuditService(repository.session).record(
                    context=context,
                    event_type="integration.authorization_denied",
                    entity_type="integration_connection",
                    entity_id=None,
                    payload={"reason": "invalid_oauth_state"},
                )
        if claimed is None:
            raise IntegrationError("integration_oauth_state_invalid")
        async with self._transaction(context) as (repository, vault):
            connection = await _get(repository, claimed.connection_id)
            verifier = await vault.load(
                context=context,
                reference=claimed.verifier_ref,
                purpose=PKCE_PURPOSE,
                record_context=claimed.verifier_context,
            )
            await repository.detach_verifier(claimed.state_digest)
            await vault.delete(
                context=context,
                reference=claimed.verifier_ref,
                purpose=PKCE_PURPOSE,
                record_context=claimed.verifier_context,
            )
            valid = (
                connection.status == "PENDING"
                and connection.authorization_version == claimed.authorization_version
                and hmac.compare_digest(
                    pkce_challenge(verifier.reveal()), claimed.code_challenge
                )
            )
            if not valid:
                await _audit(repository, connection, "authorization_denied")
            else:
                provider = self._providers.get(connection.connector_name)
                try:
                    grant = await provider.exchange(code=code, verifier=verifier)
                    _validate_grant(grant, connection, now=self._now())
                except Exception as error:
                    connection = replace(
                        connection,
                        status="REAUTH_REQUIRED",
                        health=provider_failure_health(error, now=self._now()),
                    )
                    await repository.save(connection)
                    await _audit(repository, connection, "authorization_failed")
                else:
                    connection = await self._replace_credential(
                        repository, vault, connection, grant
                    )
                    await _audit(repository, connection, "connected")
        if not valid:
            raise IntegrationError("integration_oauth_state_invalid")
        return connection.summary()

    async def connect_api_key(
        self,
        *,
        context: TenantContext,
        connector_name: str,
        credential: ResolvedSecret,
        connection_id: UUID | None = None,
    ) -> ConnectionSummary:
        provider = self._providers.get(connector_name)
        if provider.oauth is not None or connector_name != "woocommerce":
            raise IntegrationError("integration_api_key_unsupported", status=400)
        async with self._transaction(context) as (repository, vault):
            if connection_id is None:
                connection = IntegrationConnection(
                    id=new_uuid7(),
                    tenant_id=context.tenant_id,
                    connector_name=connector_name,
                    auth_kind="API_KEY",
                )
                await repository.insert(connection)
            else:
                connection = await _get(repository, connection_id)
                if (
                    connection.connector_name != connector_name
                    or connection.status == "REVOKING"
                ):
                    raise IntegrationError("integration_reconnect_invalid")
            try:
                await provider.check_health(credential)
            except Exception as error:
                connection = replace(
                    connection,
                    status="REAUTH_REQUIRED",
                    health=provider_failure_health(error, now=self._now()),
                )
                await repository.save(connection)
                await _audit(repository, connection, "authorization_failed")
            else:
                connection = await self._replace_credential(
                    repository, vault, connection, AuthorizationGrant(credential)
                )
                await _audit(repository, connection, "connected")
        return connection.summary()

    async def refresh(
        self, *, context: TenantContext, connection_id: UUID
    ) -> ConnectionSummary:
        async with self._transaction(context) as (repository, vault):
            # The same row lock serializes refresh, reconnect and revocation.
            connection = await _get(repository, connection_id)
            _require_connected(connection)
            provider = self._providers.get(connection.connector_name)
            if provider.oauth is None:
                raise IntegrationError("integration_refresh_unsupported", status=400)
            credential = await _load_credential(vault, context, connection)
            try:
                grant = await provider.refresh(credential)
                _validate_grant(grant, connection, now=self._now())
            except Exception as error:
                connection = replace(
                    connection,
                    health=provider_failure_health(error, now=self._now()),
                )
                if connection.health.status == "REAUTH_REQUIRED" or _expired(
                    connection, self._now()
                ):
                    connection = replace(connection, status="REAUTH_REQUIRED")
                await repository.save(connection)
                await _audit(repository, connection, "refresh_failed")
            else:
                connection = await self._replace_credential(
                    repository, vault, connection, grant
                )
                await _audit(repository, connection, "refreshed")
        return connection.summary()

    async def check_health(
        self, *, context: TenantContext, connection_id: UUID
    ) -> ConnectionSummary:
        async with self._transaction(context) as (repository, vault):
            connection = await _get(repository, connection_id)
            if connection.status != "CONNECTED":
                return connection.summary()
            if _expired(connection, self._now()):
                connection = replace(
                    connection,
                    status="REAUTH_REQUIRED",
                    health=ConnectorHealth(
                        status="REAUTH_REQUIRED",
                        checked_at=self._now(),
                        error_code="credentials_expired",
                    ),
                )
            else:
                credential = await _load_credential(vault, context, connection)
                provider = self._providers.get(connection.connector_name)
                try:
                    await provider.check_health(credential)
                except Exception as error:
                    health = provider_failure_health(error, now=self._now())
                else:
                    health = ConnectorHealth(status="HEALTHY", checked_at=self._now())
                connection = replace(connection, health=health)
                if health.status == "REAUTH_REQUIRED":
                    connection = replace(connection, status="REAUTH_REQUIRED")
            await repository.save(connection)
            await _audit(repository, connection, "health_checked")
        return connection.summary()

    async def revoke(
        self, *, context: TenantContext, connection_id: UUID
    ) -> ConnectionSummary:
        async with self._transaction(context) as (repository, _vault):
            connection = await _get(repository, connection_id)
            if connection.status == "REVOKED":
                return connection.summary()
            connection = replace(
                connection,
                status="REVOKING",
                authorization_version=connection.authorization_version + 1,
                health=ConnectorHealth(
                    status="ERROR",
                    checked_at=self._now(),
                    error_code="revocation_pending",
                ),
            )
            await repository.save(connection)
            await _audit(repository, connection, "revocation_started")
        # Local disable is already durable if the process/provider now fails.
        async with self._transaction(context) as (repository, vault):
            connection = await _get(repository, connection_id)
            if connection.status == "REVOKED":
                return connection.summary()
            if connection.credential_ref is not None:
                credential = await _load_credential(vault, context, connection)
                provider = self._providers.get(connection.connector_name)
                try:
                    await provider.revoke(credential)
                except Exception as error:
                    connection = replace(
                        connection,
                        health=provider_failure_health(error, now=self._now()),
                    )
                    await repository.save(connection)
                    await _audit(repository, connection, "revocation_failed")
                    return connection.summary()
            previous = connection
            connection = replace(
                connection,
                credential_ref=None,
                status="REVOKED",
                expires_at=None,
                health=ConnectorHealth(
                    status="REAUTH_REQUIRED", checked_at=self._now()
                ),
            )
            await repository.save(connection)
            await _delete_credential(vault, context, previous)
            await _audit(repository, connection, "revoked")
        return connection.summary()

    async def _replace_credential(
        self,
        repository: IntegrationRepository,
        vault: SecretVault,
        connection: IntegrationConnection,
        grant: AuthorizationGrant,
    ) -> IntegrationConnection:
        reference = await vault.store(
            context=repository.context,
            purpose=connection.credential_purpose,
            record_context=connection.credential_context,
            plaintext=grant.credential.reveal(),
        )
        updated = replace(
            connection,
            credential_ref=reference,
            status="CONNECTED",
            granted_scopes=tuple(sorted(set(grant.granted_scopes))),
            expires_at=grant.expires_at,
            health=ConnectorHealth(status="HEALTHY", checked_at=self._now()),
        )
        await repository.save(updated)
        await _delete_credential(vault, repository.context, connection)
        return updated


async def _get(
    repository: IntegrationRepository, connection_id: UUID
) -> IntegrationConnection:
    connection = await repository.get(connection_id, lock=True)
    if connection is None:
        raise IntegrationError("integration_connection_not_found", status=404)
    return connection


def _require_connected(connection: IntegrationConnection) -> None:
    if (
        connection.status not in {"CONNECTED", "REAUTH_REQUIRED"}
        or connection.credential_ref is None
    ):
        raise IntegrationError("integration_not_connected")


def _expired(connection: IntegrationConnection, now: datetime) -> bool:
    return connection.expires_at is not None and connection.expires_at <= now


def _validate_grant(
    grant: AuthorizationGrant, connection: IntegrationConnection, *, now: datetime
) -> None:
    if set(grant.granted_scopes) != set(connection.requested_scopes):
        raise IntegrationError("integration_scopes_invalid")
    if grant.expires_at is not None and (
        grant.expires_at.tzinfo is None or grant.expires_at <= now
    ):
        raise IntegrationError("integration_credentials_expired")


async def _load_credential(
    vault: SecretVault, context: TenantContext, connection: IntegrationConnection
) -> ResolvedSecret:
    if connection.credential_ref is None:
        raise IntegrationError("integration_not_connected")
    return await vault.load(
        context=context,
        reference=connection.credential_ref,
        purpose=connection.credential_purpose,
        record_context=connection.credential_context,
    )


async def _delete_credential(
    vault: SecretVault, context: TenantContext, connection: IntegrationConnection
) -> None:
    if connection.credential_ref is not None:
        await vault.delete(
            context=context,
            reference=connection.credential_ref,
            purpose=connection.credential_purpose,
            record_context=connection.credential_context,
        )


async def _audit(
    repository: IntegrationRepository, connection: IntegrationConnection, operation: str
) -> None:
    await AuditService(repository.session).record(
        context=repository.context,
        event_type=f"integration.{operation}",
        entity_type="integration_connection",
        entity_id=connection.id,
        payload={
            "connector": connection.connector_name,
            "status": connection.status,
            "health_status": connection.health.status,
            "error_code": connection.health.error_code,
            "requested_scopes": list(connection.requested_scopes),
            "granted_scopes": list(connection.granted_scopes),
            "authorization_version": connection.authorization_version,
        },
    )
