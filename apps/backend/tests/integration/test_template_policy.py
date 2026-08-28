from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.whatsapp.contracts import (
    OutboundTemplateRequest,
    OutboundTextRequest,
    ProviderMessageResult,
)
from agents_factory.modules.whatsapp.outbound_service import (
    ApprovedTemplateRequired,
    OutboundMessageService,
)
from agents_factory.modules.whatsapp.template_service import (
    SyncedWhatsAppTemplate,
    TemplatePolicyViolation,
    TemplateService,
)


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


async def _seed_account(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    label: str,
) -> tuple[UUID, UUID]:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, :name, 'active')"
            ),
            {"id": tenant_id, "slug": f"template-{label}", "name": label},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', :waba_id, :phone_number_id, "
                "'active')"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "waba_id": f"waba-{label}",
                "phone_number_id": f"phone-{label}",
            },
        )
    return tenant_id, account_id


class NeverCalledProvider:
    def __init__(self) -> None:
        self.text_requests: list[OutboundTextRequest] = []

    async def send_text(self, request: OutboundTextRequest) -> ProviderMessageResult:
        self.text_requests.append(request)
        raise AssertionError("expired free-form text reached the provider")

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult:
        raise AssertionError(f"unexpected template send: {request}")


async def _seed_expired_text_reply(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    tenant_id, account_id = await _seed_account(session_factory, label="expired")
    conversation_id = new_uuid7()
    inbound_id = new_uuid7()
    assistant_id = new_uuid7()
    occurred_at = datetime.now(UTC) - timedelta(hours=25)
    insert_message = text(
        "INSERT INTO public.messages "
        "(id, tenant_id, conversation_id, in_reply_to_message_id, direction, "
        "sender_type, provider_message_id, message_type, content, "
        "provider_timestamp, arrival_sequence, agent_spec_id, "
        "agent_spec_version) VALUES "
        "(:id, :tenant_id, :conversation_id, :reply_to, :direction, "
        ":sender_type, :provider_message_id, 'text', :content, "
        ":provider_timestamp, :arrival_sequence, :agent_spec_id, "
        ":agent_spec_version)"
    ).bindparams(bindparam("content", type_=JSONB))
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant_id, :account_id, '573000000001')"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "account_id": account_id,
            },
        )
        await session.execute(
            insert_message,
            {
                "id": inbound_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "reply_to": None,
                "direction": "inbound",
                "sender_type": "customer",
                "provider_message_id": f"wamid.inbound.{inbound_id}",
                "content": {"text": "Hola"},
                "provider_timestamp": occurred_at,
                "arrival_sequence": 1,
                "agent_spec_id": None,
                "agent_spec_version": None,
            },
        )
        await session.execute(
            insert_message,
            {
                "id": assistant_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "reply_to": inbound_id,
                "direction": "outbound",
                "sender_type": "ai",
                "provider_message_id": None,
                "content": {"text": "Respuesta vencida"},
                "provider_timestamp": occurred_at + timedelta(seconds=1),
                "arrival_sequence": 2,
                "agent_spec_id": new_uuid7(),
                "agent_spec_version": "m2-test",
            },
        )
    return tenant_id, assistant_id


def _approved_template() -> SyncedWhatsAppTemplate:
    return SyncedWhatsAppTemplate(
        provider_template_id="meta-template-1",
        name="appointment_confirmation",
        language="es_CO",
        status="APPROVED",
        category="UTILITY",
        variable_names=("customer_name", "appointment_time"),
    )


@pytest.mark.asyncio
async def test_approved_template_prepares_one_ordered_proactive_send(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, account_id = await _seed_account(session_factory, label="approved")
    service = TemplateService(
        session_factory=session_factory,
        context=_context(tenant_id),
    )
    await service.sync(
        whatsapp_account_id=account_id,
        templates=(_approved_template(),),
    )

    outbound_id = await service.prepare_proactive(
        whatsapp_account_id=account_id,
        recipient_wa_id="573000000001",
        template_name="appointment_confirmation",
        language="es_CO",
        variables={
            "appointment_time": "28 de agosto, 10:00",
            "customer_name": "Daniel",
        },
        idempotency_key="appointment-confirmation:appointment-1",
    )
    duplicate_id = await service.prepare_proactive(
        whatsapp_account_id=account_id,
        recipient_wa_id="573000000001",
        template_name="appointment_confirmation",
        language="es_CO",
        variables={
            "customer_name": "Daniel",
            "appointment_time": "28 de agosto, 10:00",
        },
        idempotency_key="appointment-confirmation:appointment-1",
    )

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT kind, payload, status FROM public.outbound_messages "
                        "WHERE id = :id"
                    ),
                    {"id": outbound_id},
                )
            )
            .mappings()
            .one()
        )
        send_jobs = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE topic = 'whatsapp.outbound.send'"
            )
        )

    assert duplicate_id == outbound_id
    assert row["kind"] == "template"
    assert row["status"] == "PREPARED"
    assert row["payload"] == {
        "template_name": "appointment_confirmation",
        "language": "es_CO",
        "variable_names": ["customer_name", "appointment_time"],
        "body_parameters": ["Daniel", "28 de agosto, 10:00"],
    }
    assert send_jobs == 1


@pytest.mark.asyncio
async def test_unapproved_template_cannot_initiate_proactive_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, account_id = await _seed_account(session_factory, label="pending")
    service = TemplateService(
        session_factory=session_factory,
        context=_context(tenant_id),
    )
    pending = SyncedWhatsAppTemplate(
        provider_template_id="meta-template-pending",
        name="appointment_confirmation",
        language="es_CO",
        status="PENDING",
        category="UTILITY",
        variable_names=("customer_name", "appointment_time"),
    )
    await service.sync(whatsapp_account_id=account_id, templates=(pending,))

    with pytest.raises(ApprovedTemplateRequired):
        await service.prepare_proactive(
            whatsapp_account_id=account_id,
            recipient_wa_id="573000000001",
            template_name=pending.name,
            language=pending.language,
            variables={
                "customer_name": "Daniel",
                "appointment_time": "28 de agosto, 10:00",
            },
            idempotency_key="pending-template-attempt",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_case", ["ownership", "language", "variables"])
async def test_template_policy_rejects_invalid_binding(
    session_factory: async_sessionmaker[AsyncSession],
    invalid_case: str,
) -> None:
    tenant_a, account_a = await _seed_account(
        session_factory, label=f"a-{invalid_case}"
    )
    tenant_b, account_b = await _seed_account(
        session_factory, label=f"b-{invalid_case}"
    )
    service_a = TemplateService(
        session_factory=session_factory,
        context=_context(tenant_a),
    )
    service_b = TemplateService(
        session_factory=session_factory,
        context=_context(tenant_b),
    )
    await service_a.sync(
        whatsapp_account_id=account_a,
        templates=(_approved_template(),),
    )
    await service_b.sync(
        whatsapp_account_id=account_b,
        templates=(_approved_template(),),
    )
    target_account = account_b if invalid_case == "ownership" else account_a
    language = "en_US" if invalid_case == "language" else "es_CO"
    variables = (
        {"customer_name": "Daniel"}
        if invalid_case == "variables"
        else {
            "customer_name": "Daniel",
            "appointment_time": "28 de agosto, 10:00",
        }
    )

    with pytest.raises(TemplatePolicyViolation):
        await service_a.prepare_proactive(
            whatsapp_account_id=target_account,
            recipient_wa_id="573000000001",
            template_name="appointment_confirmation",
            language=language,
            variables=variables,
            idempotency_key=f"invalid-{invalid_case}",
        )


@pytest.mark.asyncio
async def test_free_form_text_outside_service_window_requires_template(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, assistant_id = await _seed_expired_text_reply(session_factory)
    provider = NeverCalledProvider()
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )

    with pytest.raises(ApprovedTemplateRequired):
        await service.prepare_text(message_id=assistant_id)

    assert provider.text_requests == []
