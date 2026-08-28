from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.database import set_tenant_context
from agents_factory.modules.secrets.contracts import KeyEncryptionProvider, SecretRef
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.contracts import (
    CoexistenceEligibility,
    MetaEmbeddedSignupProvider,
    WhatsAppHealthStatus,
    WhatsAppMode,
)
from agents_factory.modules.whatsapp.signup_service import (
    ACCESS_TOKEN_PURPOSE,
    ConnectedWhatsAppAccount,
)


class WhatsAppAccountError(DomainError):
    def __init__(self, *, code: str, detail: str, status: int = 409) -> None:
        super().__init__(
            type=f"https://agents-factory.dev/problems/{code.replace('_', '-')}",
            title="WhatsApp Account Error",
            status=status,
            detail=detail,
            code=code,
        )


@dataclass(frozen=True, slots=True)
class WhatsAppAccountSummary:
    id: UUID
    business_id: str | None
    waba_id: str
    phone_number_id: str
    status: str
    mode: WhatsAppMode
    coexistence_eligibility: CoexistenceEligibility
    granted_scopes: tuple[str, ...]
    health_status: WhatsAppHealthStatus
    last_health_checked_at: datetime | None
    token_expires_at: datetime | None
    verified_at: datetime | None

    @classmethod
    def from_account(cls, account: ConnectedWhatsAppAccount) -> WhatsAppAccountSummary:
        return cls(
            id=account.id,
            business_id=account.business_id,
            waba_id=account.waba_id,
            phone_number_id=account.phone_number_id,
            status=account.status,
            mode=account.mode,
            coexistence_eligibility=account.coexistence_eligibility,
            granted_scopes=account.granted_scopes,
            health_status=account.health_status,
            last_health_checked_at=account.last_health_checked_at,
            token_expires_at=account.token_expires_at,
            verified_at=account.verified_at,
        )


class WhatsAppAccountRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        state_session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session = session
        self._state_session_factory = state_session_factory

    async def save_signup_state(
        self,
        *,
        state_digest: str,
        tenant_id: UUID,
        admin_user_id: UUID,
        admin_session_id: UUID,
        expires_at: datetime,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO agents_factory_private.whatsapp_signup_states "
                "(state_digest, tenant_id, admin_user_id, admin_session_id, expires_at) "
                "VALUES (:state_digest, :tenant_id, :admin_user_id, "
                ":admin_session_id, :expires_at)"
            ),
            {
                "state_digest": state_digest,
                "tenant_id": tenant_id,
                "admin_user_id": admin_user_id,
                "admin_session_id": admin_session_id,
                "expires_at": expires_at,
            },
        )

    async def consume_signup_state(
        self,
        *,
        state_digest: str,
        tenant_id: UUID,
        admin_user_id: UUID,
        admin_session_id: UUID,
        consumed_at: datetime,
    ) -> bool:
        parameters = {
            "state_digest": state_digest,
            "tenant_id": tenant_id,
            "admin_user_id": admin_user_id,
            "admin_session_id": admin_session_id,
            "consumed_at": consumed_at,
        }
        if self._state_session_factory is None:
            consumed = await self._session.scalar(_CONSUME_SIGNUP_STATE, parameters)
        else:
            # Commit independently so a failed provider callback cannot make
            # an already-consumed state reusable.
            async with self._state_session_factory.begin() as state_session:
                await state_session.execute(text("SET LOCAL ROLE agents_factory_admin"))
                consumed = await state_session.scalar(_CONSUME_SIGNUP_STATE, parameters)
        return consumed is not None

    async def lock_phone_number(self, *, phone_number_id: str) -> None:
        await self._session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('meta:' || :phone_number_id, 0))"
            ),
            {"phone_number_id": phone_number_id},
        )

    async def find_by_phone_number(
        self, *, phone_number_id: str
    ) -> ConnectedWhatsAppAccount | None:
        row = (
            (
                await self._session.execute(
                    text(f"{_ACCOUNT_SELECT} WHERE phone_number_id = :phone_number_id"),
                    {"phone_number_id": phone_number_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _account_from_row(row)

    async def connect_account(
        self,
        *,
        account_id: UUID,
        context: TenantContext,
        business_id: str,
        waba_id: str,
        phone_number_id: str,
        access_token_secret_ref: SecretRef,
        mode: WhatsAppMode,
        coexistence_eligibility: CoexistenceEligibility,
        granted_scopes: tuple[str, ...],
        token_expires_at: datetime | None,
        verified_at: datetime,
    ) -> ConnectedWhatsAppAccount:
        statement = text(
            "INSERT INTO public.whatsapp_accounts "
            "(id, tenant_id, provider, business_id, waba_id, phone_number_id, "
            "status, "
            "access_token_secret_id, mode, coexistence_eligibility, granted_scopes, "
            "health_status, last_health_checked_at, token_expires_at, verified_at) "
            "VALUES (:id, :tenant_id, 'meta', :business_id, :waba_id, "
            ":phone_number_id, 'active', "
            ":secret_id, :mode, :eligibility, :scopes, 'HEALTHY', :verified_at, "
            ":token_expires_at, :verified_at) "
            "ON CONFLICT (provider, phone_number_id) DO UPDATE SET "
            "business_id = EXCLUDED.business_id, waba_id = EXCLUDED.waba_id, "
            "status = 'active', "
            "access_token_secret_id = EXCLUDED.access_token_secret_id, "
            "mode = EXCLUDED.mode, "
            "coexistence_eligibility = EXCLUDED.coexistence_eligibility, "
            "granted_scopes = EXCLUDED.granted_scopes, health_status = 'HEALTHY', "
            "last_health_checked_at = EXCLUDED.last_health_checked_at, "
            "last_error_code = NULL, token_expires_at = EXCLUDED.token_expires_at, "
            "verified_at = EXCLUDED.verified_at, updated_at = now() "
            "WHERE whatsapp_accounts.tenant_id = EXCLUDED.tenant_id "
            "RETURNING id"
        ).bindparams(bindparam("scopes", type_=JSONB))
        persisted_id = await self._session.scalar(
            statement,
            {
                "id": account_id,
                "tenant_id": context.tenant_id,
                "business_id": business_id,
                "waba_id": waba_id,
                "phone_number_id": phone_number_id,
                "secret_id": access_token_secret_ref.id,
                "mode": mode,
                "eligibility": coexistence_eligibility,
                "scopes": list(granted_scopes),
                "token_expires_at": token_expires_at,
                "verified_at": verified_at,
            },
        )
        if not isinstance(persisted_id, UUID):
            raise WhatsAppAccountError(
                code="whatsapp_phone_already_connected",
                detail="This WhatsApp phone number is already connected.",
            )
        account = await self.get(context=context, account_id=persisted_id)
        if account is None:
            raise RuntimeError("connected WhatsApp account is not visible")
        return account

    async def list_for_tenant(
        self, *, context: TenantContext
    ) -> tuple[ConnectedWhatsAppAccount, ...]:
        await set_tenant_context(self._session, context.tenant_id)
        rows = (
            (
                await self._session.execute(
                    text(
                        f"{_ACCOUNT_SELECT} WHERE tenant_id = :tenant_id "
                        "ORDER BY created_at"
                    ),
                    {"tenant_id": context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(_account_from_row(row) for row in rows)

    async def get(
        self, *, context: TenantContext, account_id: UUID
    ) -> ConnectedWhatsAppAccount | None:
        await set_tenant_context(self._session, context.tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        f"{_ACCOUNT_SELECT} WHERE tenant_id = :tenant_id "
                        "AND id = :account_id"
                    ),
                    {"tenant_id": context.tenant_id, "account_id": account_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _account_from_row(row)

    async def update_health(
        self,
        *,
        context: TenantContext,
        account_id: UUID,
        status: WhatsAppHealthStatus,
        error_code: str | None,
        checked_at: datetime,
    ) -> ConnectedWhatsAppAccount:
        await set_tenant_context(self._session, context.tenant_id)
        await self._session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET health_status = :status, "
                "last_error_code = :error_code, last_health_checked_at = :checked_at, "
                "updated_at = now() WHERE tenant_id = :tenant_id AND id = :account_id"
            ),
            {
                "status": status,
                "error_code": error_code,
                "checked_at": checked_at,
                "tenant_id": context.tenant_id,
                "account_id": account_id,
            },
        )
        return await self._required(context=context, account_id=account_id)

    async def deactivate(
        self,
        *,
        context: TenantContext,
        account_id: UUID,
        checked_at: datetime,
        error_code: str | None = None,
    ) -> ConnectedWhatsAppAccount:
        await set_tenant_context(self._session, context.tenant_id)
        await self._session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET status = 'inactive', "
                "health_status = 'REAUTH_REQUIRED', "
                "last_error_code = :error_code, last_health_checked_at = :checked_at, "
                "updated_at = now() WHERE tenant_id = :tenant_id AND id = :account_id"
            ),
            {
                "checked_at": checked_at,
                "error_code": error_code,
                "tenant_id": context.tenant_id,
                "account_id": account_id,
            },
        )
        return await self._required(context=context, account_id=account_id)

    async def clear_secret_reference(
        self, *, context: TenantContext, account_id: UUID
    ) -> ConnectedWhatsAppAccount:
        await set_tenant_context(self._session, context.tenant_id)
        await self._session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET access_token_secret_id = NULL, "
                "updated_at = now() WHERE tenant_id = :tenant_id AND id = :account_id"
            ),
            {"tenant_id": context.tenant_id, "account_id": account_id},
        )
        return await self._required(context=context, account_id=account_id)

    async def _required(
        self, *, context: TenantContext, account_id: UUID
    ) -> ConnectedWhatsAppAccount:
        account = await self.get(context=context, account_id=account_id)
        if account is None:
            raise _account_not_found()
        return account


class DatabaseMetaAccessTokenResolver:
    def __init__(
        self,
        *,
        session: AsyncSession,
        key_provider: KeyEncryptionProvider,
    ) -> None:
        self._repository = WhatsAppAccountRepository(session)
        self._vault = SecretVault.for_session(session, key_provider=key_provider)

    async def resolve(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
    ) -> ResolvedSecret:
        account = await self._repository.get(
            context=context, account_id=whatsapp_account_id
        )
        if (
            account is None
            or account.status != "active"
            or account.access_token_secret_ref is None
        ):
            raise _account_not_found()
        return await self._vault.load(
            context=context,
            reference=account.access_token_secret_ref,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=_record_context(account.id),
        )


class SessionFactoryMetaAccessTokenResolver:
    """Resolve one credential inside a short tenant-scoped worker transaction."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: KeyEncryptionProvider,
    ) -> None:
        self._session_factory = session_factory
        self._key_provider = key_provider

    async def resolve(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
    ) -> ResolvedSecret:
        async with self._session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await DatabaseMetaAccessTokenResolver(
                session=session,
                key_provider=self._key_provider,
            ).resolve(
                context=context,
                whatsapp_account_id=whatsapp_account_id,
            )


class WhatsAppDisconnectExecutor(Protocol):
    async def revoke(
        self, *, context: TenantContext, account_id: UUID, revoked_at: datetime
    ) -> ConnectedWhatsAppAccount: ...


class WhatsAppDisconnectCoordinator:
    """Commit local disconnection before any vault or provider cleanup."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: KeyEncryptionProvider,
        provider: MetaEmbeddedSignupProvider,
    ) -> None:
        self._session_factory = session_factory
        self._key_provider = key_provider
        self._provider = provider

    async def revoke(
        self, *, context: TenantContext, account_id: UUID, revoked_at: datetime
    ) -> ConnectedWhatsAppAccount:
        original, disconnected = await self._commit_local_disconnect(
            context=context,
            account_id=account_id,
            revoked_at=revoked_at,
        )
        secret_ref = original.access_token_secret_ref
        if secret_ref is None:
            return disconnected

        resolved_access = await self._load_old_token(
            context=context,
            account_id=original.id,
            secret_ref=secret_ref,
        )
        deleted = await self._delete_old_secret(
            context=context,
            account_id=original.id,
            secret_ref=secret_ref,
        )
        remote_revoked = False
        if resolved_access is not None:
            try:
                await self._provider.revoke(access_token=resolved_access)
                remote_revoked = True
            except Exception:
                pass
        if not (deleted and remote_revoked):
            return disconnected
        return await self._clear_pending_if_current_disconnect(
            context=context,
            account=original,
            checked_at=revoked_at,
        )

    async def _commit_local_disconnect(
        self,
        *,
        context: TenantContext,
        account_id: UUID,
        revoked_at: datetime,
    ) -> tuple[ConnectedWhatsAppAccount, ConnectedWhatsAppAccount]:
        async with self._session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            repository = WhatsAppAccountRepository(session)
            initial = await repository.get(context=context, account_id=account_id)
            if initial is None:
                raise _account_not_found()
            await repository.lock_phone_number(phone_number_id=initial.phone_number_id)
            account = await repository.get(context=context, account_id=account_id)
            if account is None:
                raise _account_not_found()
            if account.status == "inactive" and account.access_token_secret_ref is None:
                return account, account
            await repository.deactivate(
                context=context,
                account_id=account.id,
                checked_at=revoked_at,
                error_code="meta_revoke_pending",
            )
            disconnected = await repository.clear_secret_reference(
                context=context,
                account_id=account.id,
            )
            return account, disconnected

    async def _load_old_token(
        self,
        *,
        context: TenantContext,
        account_id: UUID,
        secret_ref: SecretRef,
    ) -> ResolvedSecret | None:
        try:
            async with self._session_factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
                return await SecretVault.for_session(
                    session, key_provider=self._key_provider
                ).load(
                    context=context,
                    reference=secret_ref,
                    purpose=ACCESS_TOKEN_PURPOSE,
                    record_context=_record_context(account_id),
                )
        except Exception:
            return None

    async def _delete_old_secret(
        self,
        *,
        context: TenantContext,
        account_id: UUID,
        secret_ref: SecretRef,
    ) -> bool:
        try:
            async with self._session_factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
                await SecretVault.for_session(
                    session, key_provider=self._key_provider
                ).delete(
                    context=context,
                    reference=secret_ref,
                    purpose=ACCESS_TOKEN_PURPOSE,
                    record_context=_record_context(account_id),
                )
        except Exception:
            return False
        return True

    async def _clear_pending_if_current_disconnect(
        self,
        *,
        context: TenantContext,
        account: ConnectedWhatsAppAccount,
        checked_at: datetime,
    ) -> ConnectedWhatsAppAccount:
        try:
            async with self._session_factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
                await set_tenant_context(session, context.tenant_id)
                await session.execute(
                    text(
                        "UPDATE public.whatsapp_accounts SET last_error_code = NULL, "
                        "last_health_checked_at = :checked_at, updated_at = now() "
                        "WHERE tenant_id = :tenant_id AND id = :account_id "
                        "AND status = 'inactive' AND access_token_secret_id IS NULL "
                        "AND verified_at IS NOT DISTINCT FROM :verified_at"
                    ),
                    {
                        "checked_at": checked_at,
                        "tenant_id": context.tenant_id,
                        "account_id": account.id,
                        "verified_at": account.verified_at,
                    },
                )
                current = await WhatsAppAccountRepository(session).get(
                    context=context, account_id=account.id
                )
                if current is None:
                    raise _account_not_found()
                return current
        except Exception:
            return account


class WhatsAppAccountService:
    def __init__(
        self,
        *,
        repository: WhatsAppAccountRepository,
        vault: SecretVault,
        provider: MetaEmbeddedSignupProvider,
        disconnect_executor: WhatsAppDisconnectExecutor,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._provider = provider
        self._disconnect_executor = disconnect_executor

    async def list_summaries(
        self, *, context: TenantContext
    ) -> tuple[WhatsAppAccountSummary, ...]:
        accounts = await self._repository.list_for_tenant(context=context)
        return tuple(WhatsAppAccountSummary.from_account(item) for item in accounts)

    async def check_health(
        self, *, context: TenantContext, account_id: UUID, checked_at: datetime
    ) -> WhatsAppAccountSummary:
        account = await self._required(context=context, account_id=account_id)
        resolved_access = await self._load_token(context=context, account=account)
        health = await self._provider.inspect_health(
            access_token=resolved_access,
            waba_id=account.waba_id,
            phone_number_id=account.phone_number_id,
        )
        updated = await self._repository.update_health(
            context=context,
            account_id=account.id,
            status=health.status,
            error_code=health.error_code,
            checked_at=checked_at,
        )
        return WhatsAppAccountSummary.from_account(updated)

    async def revoke(
        self, *, context: TenantContext, account_id: UUID, revoked_at: datetime
    ) -> WhatsAppAccountSummary:
        disconnected = await self._disconnect_executor.revoke(
            context=context,
            account_id=account_id,
            revoked_at=revoked_at,
        )
        return WhatsAppAccountSummary.from_account(disconnected)

    async def _required(
        self, *, context: TenantContext, account_id: UUID
    ) -> ConnectedWhatsAppAccount:
        account = await self._repository.get(context=context, account_id=account_id)
        if account is None:
            raise _account_not_found()
        return account

    async def _load_token(
        self, *, context: TenantContext, account: ConnectedWhatsAppAccount
    ) -> ResolvedSecret:
        if account.access_token_secret_ref is None:
            raise WhatsAppAccountError(
                code="whatsapp_reauthorization_required",
                detail="This WhatsApp account must be connected again.",
            )
        return await self._vault.load(
            context=context,
            reference=account.access_token_secret_ref,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=_record_context(account.id),
        )


_ACCOUNT_SELECT = (
    "SELECT id, tenant_id, business_id, waba_id, phone_number_id, status, mode, "
    "coexistence_eligibility, granted_scopes, health_status, "
    "last_health_checked_at, token_expires_at, verified_at, "
    "access_token_secret_id, created_at FROM public.whatsapp_accounts"
)


def _account_from_row(row: RowMapping) -> ConnectedWhatsAppAccount:
    scopes = row["granted_scopes"]
    return ConnectedWhatsAppAccount(
        id=row["id"],
        tenant_id=row["tenant_id"],
        business_id=row["business_id"],
        waba_id=row["waba_id"],
        phone_number_id=row["phone_number_id"],
        status=row["status"],
        mode=cast(WhatsAppMode, row["mode"]),
        coexistence_eligibility=cast(
            CoexistenceEligibility, row["coexistence_eligibility"]
        ),
        granted_scopes=tuple(
            sorted(value for value in scopes if isinstance(value, str))
        ),
        health_status=cast(WhatsAppHealthStatus, row["health_status"]),
        last_health_checked_at=row["last_health_checked_at"],
        token_expires_at=row["token_expires_at"],
        verified_at=row["verified_at"],
        access_token_secret_ref=(
            SecretRef(row["access_token_secret_id"])
            if isinstance(row["access_token_secret_id"], UUID)
            else None
        ),
    )


def _record_context(account_id: UUID) -> str:
    return f"whatsapp_account:{account_id}"


def _account_not_found() -> WhatsAppAccountError:
    return WhatsAppAccountError(
        code="whatsapp_account_not_found",
        detail="The WhatsApp account was not found.",
        status=404,
    )


_CONSUME_SIGNUP_STATE = text(
    "UPDATE agents_factory_private.whatsapp_signup_states "
    "SET consumed_at = :consumed_at "
    "WHERE state_digest = :state_digest AND tenant_id = :tenant_id "
    "AND admin_user_id = :admin_user_id "
    "AND admin_session_id = :admin_session_id "
    "AND consumed_at IS NULL AND expires_at > :consumed_at "
    "RETURNING state_digest"
)
