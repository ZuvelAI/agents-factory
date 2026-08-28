from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.secrets.contracts import SecretRef
from agents_factory.modules.whatsapp.contracts import (
    CoexistenceEligibility,
    MetaEmbeddedSignupProvider,
    WhatsAppHealthStatus,
    WhatsAppMode,
)


REQUIRED_META_SCOPES = frozenset(
    {"whatsapp_business_management", "whatsapp_business_messaging"}
)
ACCESS_TOKEN_PURPOSE = "whatsapp.meta_access_token"
_DEFAULT_STATE_TTL = timedelta(minutes=10)


class WhatsAppSignupError(DomainError):
    def __init__(self, *, code: str, detail: str, status: int = 409) -> None:
        super().__init__(
            type=f"https://agents-factory.dev/problems/{code.replace('_', '-')}",
            title="WhatsApp Connection Failed",
            status=status,
            detail=detail,
            code=code,
        )


@dataclass(frozen=True, slots=True)
class EmbeddedSignupStart:
    state: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectedWhatsAppAccount:
    id: UUID
    tenant_id: UUID
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
    access_token_secret_ref: SecretRef | None = field(repr=False)


class SignupRepository(Protocol):
    async def save_signup_state(
        self,
        *,
        state_digest: str,
        tenant_id: UUID,
        admin_user_id: UUID,
        admin_session_id: UUID,
        expires_at: datetime,
    ) -> None: ...

    async def consume_signup_state(
        self,
        *,
        state_digest: str,
        tenant_id: UUID,
        admin_user_id: UUID,
        admin_session_id: UUID,
        consumed_at: datetime,
    ) -> bool: ...

    async def find_by_phone_number(
        self, *, phone_number_id: str
    ) -> ConnectedWhatsAppAccount | None: ...

    async def lock_phone_number(self, *, phone_number_id: str) -> None: ...

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
    ) -> ConnectedWhatsAppAccount: ...


class SignupSecretVault(Protocol):
    async def store(
        self,
        *,
        context: TenantContext | None,
        purpose: str,
        record_context: str,
        plaintext: bytes,
    ) -> SecretRef: ...

    async def delete(
        self,
        *,
        context: TenantContext | None,
        reference: SecretRef,
        purpose: str,
        record_context: str,
    ) -> None: ...


class WhatsAppSignupService:
    def __init__(
        self,
        *,
        repository: SignupRepository,
        vault: SignupSecretVault,
        provider: MetaEmbeddedSignupProvider,
        now: Callable[[], datetime] | None = None,
        state_ttl: timedelta = _DEFAULT_STATE_TTL,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC))
        self._state_ttl = state_ttl

    async def start(
        self, *, context: TenantContext, admin_session_id: UUID
    ) -> EmbeddedSignupStart:
        admin_user_id = _admin_user_id(context)
        now = self._now()
        state = secrets.token_urlsafe(32)
        expires_at = now + self._state_ttl
        await self._repository.save_signup_state(
            state_digest=_state_digest(state),
            tenant_id=context.tenant_id,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            expires_at=expires_at,
        )
        return EmbeddedSignupStart(state=state, expires_at=expires_at)

    async def complete(
        self,
        *,
        context: TenantContext,
        admin_session_id: UUID,
        state: str,
        code: str,
        business_id: str,
        waba_id: str,
        phone_number_id: str,
        requested_mode: WhatsAppMode = "API_ONLY",
    ) -> ConnectedWhatsAppAccount:
        admin_user_id = _admin_user_id(context)
        now = self._now()
        consumed = await self._repository.consume_signup_state(
            state_digest=_state_digest(state),
            tenant_id=context.tenant_id,
            admin_user_id=admin_user_id,
            admin_session_id=admin_session_id,
            consumed_at=now,
        )
        if not consumed:
            raise WhatsAppSignupError(
                code="whatsapp_signup_state_invalid",
                detail="The Embedded Signup authorization session is invalid or expired.",
            )

        try:
            authorization = await self._provider.exchange_and_verify(
                code=code,
                business_id=business_id,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
            )
        except Exception:
            raise WhatsAppSignupError(
                code="meta_authorization_failed",
                detail="Meta could not verify the client-owned authorization.",
            ) from None

        if (
            authorization.business_id != business_id
            or authorization.waba_id != waba_id
            or authorization.phone_number_id != phone_number_id
            or not authorization.owns_waba
            or not authorization.owns_phone_number
        ):
            raise WhatsAppSignupError(
                code="meta_asset_ownership_invalid",
                detail="Meta did not verify ownership of the selected WhatsApp assets.",
            )
        if not REQUIRED_META_SCOPES.issubset(authorization.granted_scopes):
            raise WhatsAppSignupError(
                code="meta_scopes_missing",
                detail="The Meta authorization is missing required WhatsApp permissions.",
            )
        if (
            requested_mode == "COEXISTENCE"
            and authorization.coexistence_eligibility != "ELIGIBLE"
        ):
            raise WhatsAppSignupError(
                code="whatsapp_coexistence_ineligible",
                detail="Meta has not marked this number as eligible for Coexistence.",
            )

        await self._repository.lock_phone_number(phone_number_id=phone_number_id)
        existing = await self._repository.find_by_phone_number(
            phone_number_id=phone_number_id
        )
        if existing is not None and existing.tenant_id != context.tenant_id:
            raise WhatsAppSignupError(
                code="whatsapp_phone_already_connected",
                detail="This WhatsApp phone number is already connected.",
            )

        account_id = existing.id if existing is not None else new_uuid7()
        record_context = _secret_record_context(account_id)
        token_ref = await self._vault.store(
            context=context,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=record_context,
            plaintext=authorization.access_token.reveal(),
        )
        connected = await self._repository.connect_account(
            account_id=account_id,
            context=context,
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            access_token_secret_ref=token_ref,
            mode=requested_mode,
            coexistence_eligibility=authorization.coexistence_eligibility,
            granted_scopes=tuple(sorted(authorization.granted_scopes)),
            token_expires_at=authorization.token_expires_at,
            verified_at=now,
        )
        if (
            existing is not None
            and existing.access_token_secret_ref is not None
            and existing.access_token_secret_ref != token_ref
        ):
            await self._vault.delete(
                context=context,
                reference=existing.access_token_secret_ref,
                purpose=ACCESS_TOKEN_PURPOSE,
                record_context=record_context,
            )
        return connected


def _admin_user_id(context: TenantContext) -> UUID:
    if context.actor_type != "platform_admin" or context.actor_id is None:
        raise WhatsAppSignupError(
            code="platform_admin_required",
            detail="Platform administrator access is required.",
            status=403,
        )
    return context.actor_id


def _state_digest(state: str) -> str:
    if not isinstance(state, str) or not 16 <= len(state) <= 500:
        return hashlib.sha256(b"invalid-state").hexdigest()
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _secret_record_context(account_id: UUID) -> str:
    return f"whatsapp_account:{account_id}"
