import hmac
import re
import secrets
from dataclasses import dataclass, field
from uuid import UUID

from agents_factory.modules.approvals.tokens import ApprovalProofs
from agents_factory.modules.secrets.redaction import ResolvedSecret


@dataclass(frozen=True)
class IssuedOTP:
    plaintext: ResolvedSecret = field(repr=False)
    digest: str


def issue_otp(proofs: ApprovalProofs, challenge_id: UUID) -> IssuedOTP:
    plaintext = f"{secrets.randbelow(1_000_000):06d}"
    return IssuedOTP(
        ResolvedSecret(plaintext.encode()),
        proofs.digest("otp", f"{challenge_id}:{plaintext}"),
    )


def verify_otp(
    proofs: ApprovalProofs, challenge_id: UUID, value: str, digest: str
) -> bool:
    candidate = proofs.digest("otp", f"{challenge_id}:{value}")
    return hmac.compare_digest(candidate, digest) and bool(
        re.fullmatch(r"[0-9]{6}", value)
    )
