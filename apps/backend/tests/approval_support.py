"""Offline approvals fixture: real PostgreSQL/vault/Gmail connector, fake Google HTTP."""

import base64
import json
import re
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx

from agents_factory.modules.approvals.models import (
    ApprovalRouteDraft,
    DecideInput,
    OTPInput,
)
from agents_factory.modules.approvals.service import ApprovalService
from agents_factory.modules.approvals.tokens import ApprovalProofs
from agents_factory.modules.integrations.google.approval_mailer import (
    ApprovalMailbox,
    NativeApprovalMailer,
)
from agents_factory.modules.integrations.google.auth import (
    GMAIL_SEND,
    GoogleClientConfiguration,
    GoogleOAuthProvider,
)
from agents_factory.modules.integrations.google.base import GoogleHTTP
from agents_factory.modules.integrations.google.gmail import GmailResource
from agents_factory.modules.integrations.oauth import ProviderRegistry
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.secrets.repository import SecretVault


EMAILS = ("first@example.test", "second@example.test")
ACTION = "orders.request_order_cancellation"


class ApprovalHarness:
    def __init__(self, world):
        self.world = world
        self.clock = datetime.now(UTC)
        self.messages = []
        self.uncertain = False

    def google(self, req):
        if req.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "approval-fixture-access",
                    "refresh_token": "approval-fixture-refresh",
                    "scope": GMAIL_SEND,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if req.url.path.endswith("tokeninfo"):
            return httpx.Response(
                200,
                json={"scope": GMAIL_SEND, "issued_to": "gmail", "expires_in": 3600},
            )
        assert req.url.path == "/gmail/v1/users/me/messages/send"
        assert req.headers["Authorization"] == "Bearer approval-fixture-access"
        message = BytesParser(policy=policy.default).parsebytes(
            base64.urlsafe_b64decode(json.loads(req.content)["raw"])
        )
        self.messages.append(message)
        if self.uncertain:
            raise httpx.ReadError("fixture: delivery outcome unknown")
        return httpx.Response(200, json={"id": f"message{len(self.messages)}"})

    @classmethod
    async def create(cls, world, **route_options):
        harness = cls(world)
        transport = GoogleHTTP(httpx.MockTransport(harness.google))
        registry = ProviderRegistry()
        registry.register(
            "gmail",
            GoogleOAuthProvider(
                product="gmail",
                configuration=GoogleClientConfiguration.model_validate(
                    {
                        "client_id": "gmail",
                        "client_secret": "approval-fixture-client",
                        "redirect_uri": "https://control.example.test/callback",
                    }
                ),
                http=transport,
            ),
        )
        keys = EnvironmentMasterKeyProvider(
            environment={"APP_MASTER_KEY": "B" * 42 + "A"}
        )
        integrations = IntegrationService(
            sessions=world.sessions, key_provider=keys, providers=registry
        )
        admin_session = uuid4()
        start = await integrations.start_oauth(
            context=world.context,
            admin_session_id=admin_session,
            connector_name="gmail",
            scopes=(GMAIL_SEND,),
        )
        connection = await integrations.complete_oauth(
            context=world.context,
            admin_session_id=admin_session,
            state=parse_qs(urlsplit(start.authorization_url).query)["state"][0],
            code=ResolvedSecret(b"approval-fixture-code"),
        )
        async with world.sessions.begin() as session:
            vault = SecretVault.for_session(session, key_provider=keys)
            reference = await vault.store(
                context=world.context,
                purpose="approval_proofs",
                record_context="approval_service",
                plaintext=b"approval-fixture-proof-material!!",
            )
            proofs = await ApprovalProofs.from_vault(
                vault=vault, context=world.context, reference=reference
            )
        mailer = NativeApprovalMailer(
            integrations,
            {
                world.context.tenant_id: ApprovalMailbox(
                    uuid4(),
                    connection.id,
                    GmailResource(
                        sender="factory@example.test",
                        approval_recipients=frozenset(EMAILS),
                    ),
                )
            },
            http=transport,
        )
        harness.service = ApprovalService(
            world.sessions,
            proofs=proofs,
            mailer=mailer,
            public_origin="https://control.example.test",
            now=lambda: harness.clock,
        )
        harness.configuration = ApprovalRouteDraft(
            ref="orders-approvals",
            capability="orders",
            action=ACTION,
            authorized_emails=EMAILS,
            **route_options,
        )
        harness.route = await harness.service.save_route(
            context=world.context, configuration=harness.configuration
        )
        return harness

    async def request(self):
        world = self.world
        action = await world.request(
            next(iter(world.bindings)),
            ACTION,
            {"order_id": "42", "reason": "Customer request"},
        )
        await world.confirm(action)
        request = await self.service.request(context=world.context, action_id=action.id)
        return action, request

    async def notices(self, request):
        await self.service.send_notices(
            context=self.world.context, request_id=request.id
        )
        return {
            str(message["To"]): re.search(r"#token=(\S+)", message.get_content()).group(
                1
            )
            for message in self.messages
            if str(request.id) in message.get_content()
            and "#token=" in message.get_content()
        }

    async def verification(self, token, email=EMAILS[0], decision="APPROVE"):
        receipt = await self.service.start_otp(OTPInput(link_token=token, email=email))
        code = re.search(
            r"Código de verificación: ([0-9]{6})", self.messages[-1].get_content()
        ).group(1)
        return DecideInput(
            link_token=token,
            email=email,
            challenge_id=receipt.challenge_id,
            code=code,
            decision=decision,
            requested_result={
                "reason_code": "customer_request",
                "explanation": "Reviewed request; execution still pending.",
                "requested_next_actions": ["review_order"],
            },
        )
