from __future__ import annotations

import base64
import hashlib
from email.message import EmailMessage
from typing import Annotated, ClassVar

from pydantic import Field

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.auth import GMAIL_SEND
from agents_factory.modules.integrations.google.base import (
    GoogleConnector,
    GoogleFailure,
    InputModel,
    manifest,
    response_string,
)


Mailbox = Annotated[
    str,
    Field(
        max_length=254,
        pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$",
    ),
]


class ApprovalNotice(InputModel):
    recipient: Mailbox
    subject: str = Field(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")
    text: str = Field(min_length=1, max_length=32000)


class GmailResource(InputModel):
    sender: Mailbox
    approval_recipients: frozenset[Mailbox] = Field(min_length=1, max_length=50)


class GmailConnector(GoogleConnector[GmailResource]):
    manifest = manifest(
        "gmail", "Gmail", ("gmail.send_approval_notice",), "gmail.GmailConnector"
    )
    operation_scopes: ClassVar[dict[str, frozenset[str]]] = {
        "gmail.send_approval_notice": frozenset({GMAIL_SEND})
    }
    write_operations = frozenset({"gmail.send_approval_notice"})

    async def _execute(self, request: ConnectorRequest) -> dict[str, object]:
        notice = ApprovalNotice.model_validate(request.arguments)
        if notice.recipient not in self.resource.approval_recipients:
            raise GoogleFailure("resource_not_allowed")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = (
            self.resource.sender,
            notice.recipient,
            notice.subject,
        )
        digest = hashlib.sha256(
            f"{request.tenant_id}:{request.binding_id}:{request.idempotency_key}".encode()
        ).hexdigest()
        message["Message-ID"] = f"<{digest}@agents-factory.invalid>"
        message.set_content(notice.text)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        payload = await self.http.json(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            access=self.access,
            body={"raw": raw},
            write=True,
        )
        # Message-ID aids manual reconciliation, but Gmail does NOT guarantee dedup.
        return {"message_id": response_string(payload, "id", write=True)}
