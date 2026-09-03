from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.approvals.models import MailState
from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.factory import ConnectedGoogleConnector
from agents_factory.modules.integrations.google.gmail import GmailResource
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.secrets.redaction import ResolvedSecret


class ApprovalMailer(Protocol):
    def supports(self, tenant_id: UUID, recipients: tuple[str, ...]) -> bool: ...

    async def send(
        self,
        *,
        context: TenantContext,
        recipient: str,
        subject: str,
        body: ResolvedSecret,
        delivery_id: UUID,
    ) -> MailState: ...


@dataclass(frozen=True)
class ApprovalMailbox:
    binding_id: UUID
    connection_id: UUID
    resource: GmailResource


class NativeApprovalMailer:
    """Native Gmail with encrypted connection credentials; no bodies in audit/logs.

    The caller commits the per-link/OTP delivery claim BEFORE calling send. Gmail
    Message-ID alone isn't idempotency; ambiguous sends must not be retried blindly.
    """

    def __init__(
        self,
        integrations: IntegrationService,
        mailboxes: Mapping[UUID, ApprovalMailbox],
        *,
        http: GoogleHTTP | None = None,
    ) -> None:
        self.integrations, self.mailboxes = integrations, dict(mailboxes)
        self.http = http or GoogleHTTP()

    def supports(self, tenant_id: UUID, recipients: tuple[str, ...]) -> bool:
        mailbox = self.mailboxes.get(tenant_id)
        return mailbox is not None and set(recipients).issubset(
            mailbox.resource.approval_recipients
        )

    async def send(
        self,
        *,
        context: TenantContext,
        recipient: str,
        subject: str,
        body: ResolvedSecret,
        delivery_id: UUID,
    ) -> MailState:
        if (
            context.actor_id is None
            or context.actor_type not in {"system", "platform_admin"}
            or not self.supports(context.tenant_id, (recipient,))
        ):
            return "FAILED"
        mailbox = self.mailboxes[context.tenant_id]
        connector = ConnectedGoogleConnector(
            service=self.integrations,
            context=context,
            connection_id=mailbox.connection_id,
            product="gmail",
            binding=GoogleBinding(
                context.tenant_id,
                mailbox.binding_id,
                frozenset({"gmail.send_approval_notice"}),
            ),
            resource=mailbox.resource,
            http=self.http,
        )
        try:
            result = await connector.execute(
                ConnectorRequest(
                    tenant_id=context.tenant_id,
                    binding_id=mailbox.binding_id,
                    operation="gmail.send_approval_notice",
                    idempotency_key=str(delivery_id),
                    arguments={
                        "recipient": recipient,
                        "subject": subject,
                        "text": body.reveal().decode(),
                    },
                )
            )
        except Exception:
            return "UNCERTAIN"
        return (
            "SENT"
            if result.status == "SUCCEEDED"
            else "UNCERTAIN"
            if result.status == "UNCERTAIN"
            else "FAILED"
        )
