from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.identity.models import (
    ChallengeStatus,
    EvidenceResult,
    EvidenceScope,
    IdentityChallenge,
    IdentityEvidence,
    IdentityLevel,
    IdentityMethod,
)


class IdentityRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def recognize_whatsapp(
        self, *, customer_ref: str, recognized_at: datetime
    ) -> None:
        await self._scope()
        await self._session.execute(
            text(
                "INSERT INTO public.identity_subjects "
                "(id, tenant_id, customer_ref, whatsapp_recognized_at) "
                "VALUES (:id, :tenant_id, :customer_ref, :recognized_at) "
                "ON CONFLICT (tenant_id, customer_ref) DO UPDATE SET "
                "whatsapp_recognized_at = excluded.whatsapp_recognized_at"
            ),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "customer_ref": customer_ref,
                "recognized_at": recognized_at,
            },
        )

    async def is_whatsapp_recognized(self, *, customer_ref: str) -> bool:
        await self._scope()
        count = await self._session.scalar(
            text(
                "SELECT count(*) FROM public.identity_subjects "
                "WHERE tenant_id = :tenant_id AND customer_ref = :customer_ref "
                "AND whatsapp_recognized_at IS NOT NULL"
            ),
            {"tenant_id": self._context.tenant_id, "customer_ref": customer_ref},
        )
        return cast(int, count) == 1

    async def create_challenge(self, challenge: IdentityChallenge) -> None:
        await self._scope()
        await self._session.execute(
            text(
                "INSERT INTO public.identity_challenges "
                "(id, tenant_id, customer_ref, required_level, method, "
                "secret_digest, status, attempts, max_attempts, "
                "bound_action_ref, expires_at, created_at, completed_at) VALUES "
                "(:id, :tenant_id, :customer_ref, :required_level, :method, "
                ":secret_digest, :status, :attempts, :max_attempts, "
                ":bound_action_ref, :expires_at, :created_at, :completed_at)"
            ),
            {
                **challenge.model_dump(mode="python"),
                "required_level": int(challenge.required_level),
            },
        )

    async def lock_challenge(self, challenge_id: UUID) -> IdentityChallenge | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, customer_ref, required_level, method, "
                "secret_digest, status, attempts, max_attempts, bound_action_ref, "
                "expires_at, created_at, completed_at "
                "FROM public.identity_challenges WHERE tenant_id = :tenant_id "
                "AND id = :challenge_id FOR UPDATE"
            ),
            {"tenant_id": self._context.tenant_id, "challenge_id": challenge_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else IdentityChallenge.from_mapping(row)

    async def record_failed_attempt(
        self,
        *,
        challenge: IdentityChallenge,
        status: ChallengeStatus,
        attempted_at: datetime,
        evidence_ref_digest: str,
    ) -> IdentityChallenge:
        attempts = challenge.attempts + 1
        result = await self._session.execute(
            text(
                "UPDATE public.identity_challenges SET attempts = :attempts, "
                "status = :status, completed_at = :completed_at "
                "WHERE tenant_id = :tenant_id "
                "AND id = :challenge_id RETURNING id, tenant_id, customer_ref, "
                "required_level, method, secret_digest, status, attempts, "
                "max_attempts, bound_action_ref, expires_at, created_at, completed_at"
            ),
            {
                "attempts": attempts,
                "status": status,
                "completed_at": None if status == "PENDING" else attempted_at,
                "tenant_id": self._context.tenant_id,
                "challenge_id": challenge.id,
            },
        )
        await self.append_evidence(
            customer_ref=challenge.customer_ref,
            method=challenge.method,
            result="FAILED",
            achieved_level=IdentityLevel.LEVEL_0,
            scope="ACTION" if challenge.bound_action_ref else "SESSION",
            bound_action_ref=challenge.bound_action_ref,
            evidence_ref_digest=evidence_ref_digest,
            verified_at=attempted_at,
            expires_at=attempted_at,
        )
        return IdentityChallenge.from_mapping(result.mappings().one())

    async def pass_challenge(
        self,
        *,
        challenge: IdentityChallenge,
        evidence_ref_digest: str,
        verified_at: datetime,
        evidence_expires_at: datetime,
    ) -> IdentityEvidence:
        await self._session.execute(
            text(
                "UPDATE public.identity_challenges SET status = 'PASSED', "
                "completed_at = :verified_at WHERE tenant_id = :tenant_id "
                "AND id = :challenge_id"
            ),
            {
                "verified_at": verified_at,
                "tenant_id": self._context.tenant_id,
                "challenge_id": challenge.id,
            },
        )
        return await self.append_evidence(
            customer_ref=challenge.customer_ref,
            method=challenge.method,
            result="VERIFIED",
            achieved_level=challenge.required_level,
            scope="ACTION" if challenge.bound_action_ref else "SESSION",
            bound_action_ref=challenge.bound_action_ref,
            evidence_ref_digest=evidence_ref_digest,
            verified_at=verified_at,
            expires_at=evidence_expires_at,
        )

    async def append_evidence(
        self,
        *,
        customer_ref: str,
        method: IdentityMethod,
        result: EvidenceResult,
        achieved_level: IdentityLevel,
        scope: EvidenceScope,
        bound_action_ref: str | None,
        evidence_ref_digest: str,
        verified_at: datetime,
        expires_at: datetime,
    ) -> IdentityEvidence:
        await self._scope()
        result_row = await self._session.execute(
            text(
                "INSERT INTO public.identity_evidence "
                "(id, tenant_id, customer_ref, method, result, achieved_level, "
                "scope, bound_action_ref, evidence_ref_digest, verified_at, "
                "expires_at) VALUES (:id, :tenant_id, :customer_ref, :method, "
                ":result, :level, :scope, :bound_action_ref, :digest, "
                ":verified_at, :expires_at) RETURNING id, tenant_id, "
                "customer_ref, method, result, achieved_level, scope, "
                "bound_action_ref, evidence_ref_digest, verified_at, expires_at, "
                "consumed_at"
            ),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "customer_ref": customer_ref,
                "method": method,
                "result": result,
                "level": int(achieved_level),
                "scope": scope,
                "bound_action_ref": bound_action_ref,
                "digest": evidence_ref_digest,
                "verified_at": verified_at,
                "expires_at": expires_at,
            },
        )
        return IdentityEvidence.from_mapping(result_row.mappings().one())

    async def valid_evidence(
        self, *, customer_ref: str, action_ref: str | None, assessed_at: datetime
    ) -> tuple[IdentityEvidence, ...]:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, customer_ref, method, result, "
                "achieved_level, scope, bound_action_ref, evidence_ref_digest, "
                "verified_at, expires_at, consumed_at FROM public.identity_evidence "
                "WHERE tenant_id = :tenant_id AND customer_ref = :customer_ref "
                "AND result = 'VERIFIED' AND expires_at > :assessed_at "
                "AND consumed_at IS NULL AND (scope = 'SESSION' OR "
                "(scope = 'ACTION' AND bound_action_ref = :action_ref)) "
                "ORDER BY achieved_level DESC, verified_at DESC"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "customer_ref": customer_ref,
                "assessed_at": assessed_at,
                "action_ref": action_ref,
            },
        )
        return tuple(IdentityEvidence.from_mapping(row) for row in result.mappings())

    async def consume_evidence(
        self, *, evidence_id: UUID, consumed_at: datetime
    ) -> bool:
        await self._scope()
        result = await self._session.execute(
            text(
                "UPDATE public.identity_evidence SET consumed_at = :consumed_at "
                "WHERE tenant_id = :tenant_id AND id = :evidence_id "
                "AND scope = 'ACTION' AND consumed_at IS NULL RETURNING id"
            ),
            {
                "consumed_at": consumed_at,
                "tenant_id": self._context.tenant_id,
                "evidence_id": evidence_id,
            },
        )
        return cast(UUID | None, result.scalar_one_or_none()) is not None

    async def _scope(self) -> None:
        await set_tenant_context(self._session, self._context.tenant_id)
