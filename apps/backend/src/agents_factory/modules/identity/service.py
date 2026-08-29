from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.identity.methods import (
    ChallengeDelivery,
    HashedChallengeMethod,
    digest_evidence_reference,
)
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    ChallengeReceipt,
    ChallengeStatus,
    IdentityAssessment,
    IdentityChallenge,
    IdentityEvidence,
    IdentityLevel,
    IdentityMethod,
)


class IdentityStore(Protocol):
    async def recognize_whatsapp(
        self, *, customer_ref: str, recognized_at: datetime
    ) -> None: ...

    async def is_whatsapp_recognized(self, *, customer_ref: str) -> bool: ...

    async def create_challenge(self, challenge: IdentityChallenge) -> None: ...

    async def lock_challenge(self, challenge_id: UUID) -> IdentityChallenge | None: ...

    async def record_failed_attempt(
        self,
        *,
        challenge: IdentityChallenge,
        status: ChallengeStatus,
        attempted_at: datetime,
        evidence_ref_digest: str,
    ) -> IdentityChallenge: ...

    async def pass_challenge(
        self,
        *,
        challenge: IdentityChallenge,
        evidence_ref_digest: str,
        verified_at: datetime,
        evidence_expires_at: datetime,
    ) -> IdentityEvidence: ...

    async def valid_evidence(
        self, *, customer_ref: str, action_ref: str | None, assessed_at: datetime
    ) -> tuple[IdentityEvidence, ...]: ...

    async def consume_evidence(
        self, *, evidence_id: UUID, consumed_at: datetime
    ) -> bool: ...


class IdentityService:
    def __init__(
        self,
        *,
        context: TenantContext,
        store: IdentityStore,
        challenge_method: HashedChallengeMethod | None = None,
        delivery: ChallengeDelivery | None = None,
        challenge_ttl: timedelta = timedelta(minutes=10),
        evidence_ttl: timedelta = timedelta(minutes=30),
        max_attempts: int = 5,
    ) -> None:
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("identity max_attempts must be between 1 and 10")
        self._context = context
        self._store = store
        self._challenge_method = challenge_method
        self._delivery = delivery
        self._challenge_ttl = challenge_ttl
        self._evidence_ttl = evidence_ttl
        self._max_attempts = max_attempts

    async def recognize_whatsapp(
        self, *, customer_ref: str, recognized_at: datetime | None = None
    ) -> None:
        await self._store.recognize_whatsapp(
            customer_ref=customer_ref,
            recognized_at=recognized_at or datetime.now(UTC),
        )

    async def assess(
        self,
        customer_ref: str,
        *,
        action_ref: str | None = None,
        assessed_at: datetime | None = None,
    ) -> IdentityAssessment:
        now = assessed_at or datetime.now(UTC)
        recognized = await self._store.is_whatsapp_recognized(customer_ref=customer_ref)
        evidence = await self._store.valid_evidence(
            customer_ref=customer_ref,
            action_ref=action_ref,
            assessed_at=now,
        )
        level = IdentityLevel.LEVEL_1 if recognized else IdentityLevel.LEVEL_0
        if evidence:
            level = max(level, *(item.achieved_level for item in evidence))
        return IdentityAssessment(
            tenant_id=self._context.tenant_id,
            customer_ref=customer_ref,
            achieved_level=level,
            evidence_ids=tuple(item.id for item in evidence),
            assessed_at=now,
        )

    async def challenge(
        self,
        required_level: IdentityLevel,
        *,
        customer_ref: str,
        method: IdentityMethod,
        action_ref: str | None = None,
        created_at: datetime | None = None,
    ) -> ChallengeReceipt:
        _validate_challenge_request(
            required_level=required_level,
            method=method,
            action_ref=action_ref,
        )
        now = created_at or datetime.now(UTC)
        challenge_id = new_uuid7()
        issued_challenge = None
        if method != "EXTERNAL_AUTH":
            if self._challenge_method is None or self._delivery is None:
                raise RuntimeError("identity challenge delivery is not configured")
            issued_challenge = self._challenge_method.issue(challenge_id)
        challenge = IdentityChallenge(
            id=challenge_id,
            tenant_id=self._context.tenant_id,
            customer_ref=customer_ref,
            required_level=required_level,
            method=method,
            secret_digest=(
                None if issued_challenge is None else issued_challenge.digest
            ),
            status="PENDING",
            attempts=0,
            max_attempts=self._max_attempts,
            bound_action_ref=action_ref,
            expires_at=now + self._challenge_ttl,
            created_at=now,
            completed_at=None,
        )
        await self._store.create_challenge(challenge)
        if issued_challenge is not None:
            assert self._delivery is not None
            await self._delivery.send(
                customer_ref=customer_ref,
                method=method,
                plaintext=issued_challenge.plaintext,
            )
        return ChallengeReceipt(
            challenge_id=challenge.id,
            method=method,
            required_level=required_level,
            expires_at=challenge.expires_at,
        )

    async def verify(
        self,
        *,
        challenge_id: UUID,
        response: str,
        verified_at: datetime | None = None,
    ) -> IdentityEvidence:
        now = verified_at or datetime.now(UTC)
        challenge = await self._pending_challenge(challenge_id)
        if (
            challenge.method == "EXTERNAL_AUTH"
            or challenge.secret_digest is None
            or self._challenge_method is None
        ):
            raise _verification_failed()
        reference_digest = digest_evidence_reference(
            f"{challenge.id}:{challenge.attempts + 1}"
        )
        if now >= challenge.expires_at:
            await self._store.record_failed_attempt(
                challenge=challenge,
                status="EXPIRED",
                attempted_at=now,
                evidence_ref_digest=reference_digest,
            )
            raise _verification_failed()
        verified = self._challenge_method.verify(
            challenge_id=challenge.id,
            plaintext=response,
            expected_digest=challenge.secret_digest,
        )
        if not verified:
            next_attempt = challenge.attempts + 1
            status: ChallengeStatus = (
                "LOCKED" if next_attempt >= challenge.max_attempts else "PENDING"
            )
            await self._store.record_failed_attempt(
                challenge=challenge,
                status=status,
                attempted_at=now,
                evidence_ref_digest=reference_digest,
            )
            raise _verification_failed()
        return await self._store.pass_challenge(
            challenge=challenge,
            evidence_ref_digest=reference_digest,
            verified_at=now,
            evidence_expires_at=now + self._evidence_ttl,
        )

    async def complete_external(
        self,
        *,
        challenge_id: UUID,
        verification_reference: str,
        verified: bool,
        verified_at: datetime | None = None,
    ) -> IdentityEvidence:
        now = verified_at or datetime.now(UTC)
        challenge = await self._pending_challenge(challenge_id)
        if challenge.method != "EXTERNAL_AUTH" or now >= challenge.expires_at:
            raise _verification_failed()
        reference_digest = digest_evidence_reference(verification_reference)
        if not verified:
            await self._store.record_failed_attempt(
                challenge=challenge,
                status="FAILED",
                attempted_at=now,
                evidence_ref_digest=reference_digest,
            )
            raise _verification_failed()
        return await self._store.pass_challenge(
            challenge=challenge,
            evidence_ref_digest=reference_digest,
            verified_at=now,
            evidence_expires_at=now + self._evidence_ttl,
        )

    async def consume_action_evidence(
        self, *, evidence_id: UUID, consumed_at: datetime | None = None
    ) -> bool:
        return await self._store.consume_evidence(
            evidence_id=evidence_id,
            consumed_at=consumed_at or datetime.now(UTC),
        )

    def require_for_action(
        self,
        *,
        assessment: IdentityAssessment,
        required_level: IdentityLevel,
        authorization: AuthorizationDecision,
        action: str,
        resource_type: str,
        resource_id: str,
    ) -> None:
        same_subject = (
            assessment.tenant_id == self._context.tenant_id
            and authorization.tenant_id == self._context.tenant_id
            and assessment.customer_ref == authorization.customer_ref
        )
        same_resource_action = (
            authorization.action == action
            and authorization.resource_type == resource_type
            and authorization.resource_id == resource_id
        )
        if (
            not same_subject
            or not same_resource_action
            or assessment.achieved_level < required_level
            or not authorization.allowed
        ):
            raise DomainError(
                type="https://agents-factory.dev/problems/action-not-authorized",
                title="Action Not Authorized",
                status=403,
                detail="Identity and resource authorization requirements were not met.",
                code="action_not_authorized",
            )

    async def _pending_challenge(self, challenge_id: UUID) -> IdentityChallenge:
        challenge = await self._store.lock_challenge(challenge_id)
        if challenge is None or challenge.status != "PENDING":
            raise _verification_failed()
        return challenge


def _validate_challenge_request(
    *,
    required_level: IdentityLevel,
    method: IdentityMethod,
    action_ref: str | None,
) -> None:
    valid = (
        required_level == IdentityLevel.LEVEL_2 and method == "ADDITIONAL_VERIFICATION"
    ) or (
        required_level == IdentityLevel.LEVEL_3
        and method in {"OTP", "EXTERNAL_AUTH"}
        and action_ref is not None
    )
    if not valid:
        raise ValueError("identity challenge method does not satisfy required level")


def _verification_failed() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/identity-verification-failed",
        title="Identity Verification Failed",
        status=403,
        detail="The identity challenge could not be verified.",
        code="identity_verification_failed",
    )
