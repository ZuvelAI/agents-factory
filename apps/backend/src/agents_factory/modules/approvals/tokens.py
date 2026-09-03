import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.approvals.models import ApprovalError
from agents_factory.modules.secrets.contracts import SecretRef
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.secrets.repository import SecretVault


@dataclass(frozen=True)
class LinkClaims:
    tenant_id: UUID
    request_id: UUID
    link_id: UUID
    expires_at: datetime


class ApprovalProofs:
    """Domain-separated HMAC proofs; only digests are stored with requests/OTPs."""

    def __init__(self, signing_material: ResolvedSecret) -> None:
        if len(signing_material.reveal()) < 32:
            raise ValueError("approval signing material must contain at least 32 bytes")
        self._material = signing_material

    @classmethod
    async def from_vault(
        cls, *, vault: SecretVault, context: TenantContext, reference: SecretRef
    ) -> "ApprovalProofs":
        material = await vault.load(
            context=context,
            reference=reference,
            purpose="approval_proofs",
            record_context="approval_service",
        )
        return cls(material)

    def digest(self, purpose: str, value: str) -> str:
        return hmac.new(
            self._material.reveal(),
            f"approvals:{purpose}:{value}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def issue_link(self, claims: LinkClaims) -> ResolvedSecret:
        payload = f"a1.{claims.tenant_id.hex}.{claims.request_id.hex}.{claims.link_id.hex}.{int(claims.expires_at.timestamp())}"
        return ResolvedSecret(f"{payload}.{self.digest('link', payload)}".encode())

    def verify_link(self, value: str) -> LinkClaims:
        if not re.fullmatch(
            r"a1\.[0-9a-f]{32}\.[0-9a-f]{32}\.[0-9a-f]{32}\.[0-9]{1,11}\.[0-9a-f]{64}",
            value,
        ):
            raise ApprovalError()
        payload, signature = value.rsplit(".", 1)
        if not hmac.compare_digest(self.digest("link", payload), signature):
            raise ApprovalError()
        _, tenant, request, link, expiry = payload.split(".")
        try:
            claims = LinkClaims(
                UUID(hex=tenant),
                UUID(hex=request),
                UUID(hex=link),
                datetime.fromtimestamp(int(expiry), UTC),
            )
        except (ValueError, OverflowError, OSError):
            raise ApprovalError() from None
        if self.issue_link(claims).reveal().decode() != value:
            raise ApprovalError()
        return claims

    def audit_metadata(
        self, *, tenant_id: UUID, at: datetime, ip: str | None, user_agent: str | None
    ) -> dict[str, str]:
        metadata = {}
        scope = f"{tenant_id}:{at.date().isoformat()}:"
        if ip is not None:
            try:
                address = ipaddress.ip_address(ip)
                network = ipaddress.ip_network(
                    f"{address}/{'24' if address.version == 4 else '48'}", strict=False
                )
                metadata["ip_network_digest"] = self.digest(
                    "audit_ip", scope + str(network)
                )
            except ValueError:
                pass
        if user_agent is not None:
            metadata["user_agent_digest"] = self.digest(
                "audit_ua", scope + user_agent[:512]
            )
        return metadata


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
