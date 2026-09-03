from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import text

from agents_factory.common.ids import new_uuid7
from agents_factory.modules.handoffs.models import (
    HandoffConfiguration,
    HandoffReason,
    HumanResponseSurface,
    SurfaceBinding,
    VerifiedHumanEvent,
)
from agents_factory.modules.handoffs.service import HandoffService
from agents_factory.modules.handoffs.surfaces import HumanSurfaceRegistry


class Surface:
    surface = HumanResponseSurface.EXTERNAL_INBOX
    verified = True
    event = None

    async def verify(self, **kwargs):
        return self.verified

    async def load_event(self, event_ref):
        assert event_ref == "verified-fixture"
        return self.event


class HandoffHarness:
    @classmethod
    async def create(
        cls, sessions, context, conversation_id, *, surface=None, configuration=None
    ):
        self = cls()
        self.sessions = sessions
        self.context = replace(
            context, actor_id=new_uuid7(), actor_type="platform_admin"
        )
        self.conversation_id = conversation_id
        self.surface = surface or Surface()
        self.binding = SurfaceBinding(
            surface=self.surface.surface, adapter="fixture", binding_id="verified-inbox"
        )
        self.clock = datetime.now(UTC)
        self.service = HandoffService(
            sessions,
            surfaces=HumanSurfaceRegistry({"fixture": self.surface}),
            now=lambda: self.clock,
        )
        async with sessions.begin() as session:
            self.account_id = await session.scalar(
                text(
                    "SELECT whatsapp_account_id FROM public.conversations WHERE id=:id"
                ),
                {"id": conversation_id},
            )
            await session.execute(
                text(
                    "UPDATE public.messages SET provider_timestamp=now() WHERE conversation_id=:id"
                ),
                {"id": conversation_id},
            )
        self.configuration = configuration or HandoffConfiguration(
            enabled=True, surface=self.binding
        )
        await self.service.configure(
            context=self.context,
            account_id=self.account_id,
            configuration=self.configuration,
        )
        return self

    async def request(self):
        return await self.service.request(
            context=self.context,
            conversation_id=self.conversation_id,
            reason=HandoffReason.EXPLICIT_REQUEST,
        )

    async def human_event(self, record, *, kind="ACTIVATE", sequence=0, **changes):
        self.surface.event = VerifiedHumanEvent(
            tenant_id=self.context.tenant_id,
            whatsapp_account_id=self.account_id,
            conversation_id=self.conversation_id,
            handoff_id=record.id,
            binding=self.binding,
            event_id=f"event-{sequence}",
            sequence=sequence,
            kind=kind,
            occurred_at=self.clock,
        ).model_copy(update=changes)
        return await self.service.handle_event(
            context=self.context, binding=self.binding, event_ref="verified-fixture"
        )


async def activate_verified_handoff(sessions, context, conversation_id):
    harness = await HandoffHarness.create(sessions, context, conversation_id)
    return await harness.human_event(await harness.request())
