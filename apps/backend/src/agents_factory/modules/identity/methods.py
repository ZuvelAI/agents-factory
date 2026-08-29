from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from agents_factory.modules.identity.models import IdentityMethod


@dataclass(frozen=True, slots=True)
class IssuedChallengeSecret:
    plaintext: str = field(repr=False)
    digest: str


class ChallengeDelivery(Protocol):
    async def send(
        self,
        *,
        customer_ref: str,
        method: IdentityMethod,
        plaintext: str,
    ) -> None: ...


class HashedChallengeMethod:
    def __init__(self, *, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("identity challenge pepper must be at least 32 bytes")
        self._pepper = pepper

    def issue(self, challenge_id: UUID) -> IssuedChallengeSecret:
        plaintext = f"{secrets.randbelow(1_000_000):06d}"
        return IssuedChallengeSecret(
            plaintext=plaintext,
            digest=self.digest(challenge_id=challenge_id, plaintext=plaintext),
        )

    def verify(
        self, *, challenge_id: UUID, plaintext: str, expected_digest: str
    ) -> bool:
        candidate = self.digest(challenge_id=challenge_id, plaintext=plaintext)
        return hmac.compare_digest(candidate, expected_digest)

    def digest(self, *, challenge_id: UUID, plaintext: str) -> str:
        message = f"{challenge_id}:{plaintext}".encode()
        return hmac.new(self._pepper, message, hashlib.sha256).hexdigest()


def digest_evidence_reference(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
