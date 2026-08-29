from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.identity.methods import HashedChallengeMethod
from agents_factory.modules.identity.models import (
    ChallengeStatus,
    IdentityChallenge,
    IdentityEvidence,
    IdentityLevel,
    IdentityMethod,
)
from agents_factory.modules.identity.service import IdentityService


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)
TENANT_ID = UUID("10000000-0000-0000-0000-000000000014")


class Delivery:
    def __init__(self) -> None:
        self.plaintext: str | None = None

    async def send(
        self,
        *,
        customer_ref: str,
        method: IdentityMethod,
        plaintext: str,
    ) -> None:
        _ = (customer_ref, method)
        self.plaintext = plaintext


class Store:
    def __init__(self) -> None:
        self.recognized: set[str] = set()
        self.challenges: dict[UUID, IdentityChallenge] = {}
        self.evidence: list[IdentityEvidence] = []

    async def recognize_whatsapp(
        self, *, customer_ref: str, recognized_at: datetime
    ) -> None:
        _ = recognized_at
        self.recognized.add(customer_ref)

    async def is_whatsapp_recognized(self, *, customer_ref: str) -> bool:
        return customer_ref in self.recognized

    async def create_challenge(self, challenge: IdentityChallenge) -> None:
        self.challenges[challenge.id] = challenge

    async def lock_challenge(self, challenge_id: UUID) -> IdentityChallenge | None:
        return self.challenges.get(challenge_id)

    async def record_failed_attempt(
        self,
        *,
        challenge: IdentityChallenge,
        status: ChallengeStatus,
        attempted_at: datetime,
        evidence_ref_digest: str,
    ) -> IdentityChallenge:
        _ = evidence_ref_digest
        updated = challenge.model_copy(
            update={
                "attempts": challenge.attempts + 1,
                "status": status,
                "completed_at": None if status == "PENDING" else attempted_at,
            }
        )
        self.challenges[challenge.id] = updated
        return updated

    async def pass_challenge(
        self,
        *,
        challenge: IdentityChallenge,
        evidence_ref_digest: str,
        verified_at: datetime,
        evidence_expires_at: datetime,
    ) -> IdentityEvidence:
        self.challenges[challenge.id] = challenge.model_copy(
            update={"status": "PASSED", "completed_at": verified_at}
        )
        evidence = IdentityEvidence(
            id=uuid4(),
            tenant_id=challenge.tenant_id,
            customer_ref=challenge.customer_ref,
            method=challenge.method,
            result="VERIFIED",
            achieved_level=challenge.required_level,
            scope="ACTION" if challenge.bound_action_ref else "SESSION",
            bound_action_ref=challenge.bound_action_ref,
            evidence_ref_digest=evidence_ref_digest,
            verified_at=verified_at,
            expires_at=evidence_expires_at,
            consumed_at=None,
        )
        self.evidence.append(evidence)
        return evidence

    async def valid_evidence(
        self, *, customer_ref: str, action_ref: str | None, assessed_at: datetime
    ) -> tuple[IdentityEvidence, ...]:
        return tuple(
            item
            for item in self.evidence
            if item.customer_ref == customer_ref
            and item.result == "VERIFIED"
            and item.expires_at > assessed_at
            and item.consumed_at is None
            and (item.scope == "SESSION" or item.bound_action_ref == action_ref)
        )

    async def consume_evidence(
        self, *, evidence_id: UUID, consumed_at: datetime
    ) -> bool:
        for index, item in enumerate(self.evidence):
            if (
                item.id == evidence_id
                and item.scope == "ACTION"
                and not item.consumed_at
            ):
                self.evidence[index] = item.model_copy(
                    update={"consumed_at": consumed_at}
                )
                return True
        return False


def service(
    store: Store, delivery: Delivery, *, max_attempts: int = 5
) -> IdentityService:
    return IdentityService(
        context=TenantContext(
            tenant_id=TENANT_ID,
            actor_id=None,
            actor_type="system",
            correlation_id=uuid4(),
        ),
        store=store,
        challenge_method=HashedChallengeMethod(pepper=b"p" * 32),
        delivery=delivery,
        max_attempts=max_attempts,
    )


@pytest.mark.asyncio
async def test_unknown_and_recognized_whatsapp_are_levels_zero_and_one() -> None:
    store, delivery = Store(), Delivery()
    identity = service(store, delivery)

    assert (await identity.assess("customer", assessed_at=NOW)).achieved_level == 0
    await identity.recognize_whatsapp(customer_ref="customer", recognized_at=NOW)
    assert (await identity.assess("customer", assessed_at=NOW)).achieved_level == 1


@pytest.mark.asyncio
async def test_additional_verification_reaches_level_two_until_expiry() -> None:
    store, delivery = Store(), Delivery()
    identity = service(store, delivery)
    await identity.recognize_whatsapp(customer_ref="customer", recognized_at=NOW)
    receipt = await identity.challenge(
        IdentityLevel.LEVEL_2,
        customer_ref="customer",
        method="ADDITIONAL_VERIFICATION",
        created_at=NOW,
    )
    assert delivery.plaintext is not None
    await identity.verify(
        challenge_id=receipt.challenge_id,
        response=delivery.plaintext,
        verified_at=NOW + timedelta(seconds=1),
    )

    assert (
        await identity.assess("customer", assessed_at=NOW + timedelta(minutes=1))
    ).achieved_level == 2
    assert (
        await identity.assess("customer", assessed_at=NOW + timedelta(minutes=31))
    ).achieved_level == 1


@pytest.mark.asyncio
async def test_otp_is_action_bound_and_consumed_once() -> None:
    store, delivery = Store(), Delivery()
    identity = service(store, delivery)
    await identity.recognize_whatsapp(customer_ref="customer", recognized_at=NOW)
    receipt = await identity.challenge(
        IdentityLevel.LEVEL_3,
        customer_ref="customer",
        method="OTP",
        action_ref="action-1",
        created_at=NOW,
    )
    assert delivery.plaintext is not None
    evidence = await identity.verify(
        challenge_id=receipt.challenge_id,
        response=delivery.plaintext,
        verified_at=NOW + timedelta(seconds=1),
    )

    assert (
        await identity.assess(
            "customer", action_ref="action-2", assessed_at=NOW + timedelta(seconds=2)
        )
    ).achieved_level == 1
    assert (
        await identity.assess(
            "customer", action_ref="action-1", assessed_at=NOW + timedelta(seconds=2)
        )
    ).achieved_level == 3
    assert await identity.consume_action_evidence(
        evidence_id=evidence.id,
        consumed_at=NOW + timedelta(seconds=3),
    )
    assert (
        await identity.assess(
            "customer", action_ref="action-1", assessed_at=NOW + timedelta(seconds=4)
        )
    ).achieved_level == 1


@pytest.mark.asyncio
async def test_guessed_codes_lock_after_bounded_attempts_and_cannot_replay() -> None:
    store, delivery = Store(), Delivery()
    identity = service(store, delivery, max_attempts=2)
    receipt = await identity.challenge(
        IdentityLevel.LEVEL_2,
        customer_ref="customer",
        method="ADDITIONAL_VERIFICATION",
        created_at=NOW,
    )

    for offset in (1, 2):
        with pytest.raises(DomainError):
            await identity.verify(
                challenge_id=receipt.challenge_id,
                response="000000",
                verified_at=NOW + timedelta(seconds=offset),
            )
    assert store.challenges[receipt.challenge_id].status == "LOCKED"
    with pytest.raises(DomainError):
        await identity.verify(
            challenge_id=receipt.challenge_id,
            response=delivery.plaintext or "",
            verified_at=NOW + timedelta(seconds=3),
        )


@pytest.mark.asyncio
async def test_external_auth_can_produce_action_bound_level_three() -> None:
    store, delivery = Store(), Delivery()
    identity = service(store, delivery)
    receipt = await identity.challenge(
        IdentityLevel.LEVEL_3,
        customer_ref="customer",
        method="EXTERNAL_AUTH",
        action_ref="action-1",
        created_at=NOW,
    )
    evidence = await identity.complete_external(
        challenge_id=receipt.challenge_id,
        verification_reference="provider-assertion-opaque-ref",
        verified=True,
        verified_at=NOW + timedelta(seconds=1),
    )

    assert evidence.achieved_level == IdentityLevel.LEVEL_3
    assert evidence.evidence_ref_digest != "provider-assertion-opaque-ref"
