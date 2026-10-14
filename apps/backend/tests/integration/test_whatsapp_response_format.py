import pytest
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB

from apps.backend.tests.integration.test_outbound_idempotency import (
    _seed_text_reply,
    _context,
    RecordingProvider,
)
from agents_factory.modules.whatsapp.contracts import ProviderMessageResult
from agents_factory.modules.whatsapp.outbound_service import OutboundMessageService


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "Para entender tu empresa: **¿a qué tipo de clientes quieres llegar?**",
            "Para entender tu empresa: *¿a qué tipo de clientes quieres llegar?*",
        ),
        (
            "• **Leads**\n• *Análisis de datos para toma de decisiones*",
            "• *Leads*\n• *Análisis de datos para toma de decisiones*",
        ),
        ("***Zuvel*** y ****servicios****", "*Zuvel* y *servicios*"),
        ("Consulta **sin cierre\n• *Servicio*", "Consulta sin cierre\n• *Servicio*"),
        ("* Servicio uno\n* Servicio dos", "• Servicio uno\n• Servicio dos"),
        ("• *Servicio*\nConsulta sin formato.", "• *Servicio*\nConsulta sin formato."),
    ],
)
async def test_ai_text_sent_to_meta_has_whatsapp_bold_without_surplus_markers(
    session_factory,
    body,
    expected,
):
    tenant, _, _, assistant = await _seed_text_reply(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            text("UPDATE public.messages SET content=:content WHERE id=:id").bindparams(
                bindparam("content", type_=JSONB)
            ),
            {"id": assistant, "content": {"text": body}},
        )
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.format")]
    )
    service = OutboundMessageService(
        session_factory=session_factory, context=_context(tenant), provider=provider
    )
    prepared = await service.prepare_text(message_id=assistant)
    async with session_factory.begin() as session:
        payload = await session.scalar(
            text("SELECT payload->>'body' FROM public.outbound_messages WHERE id=:id"),
            {"id": prepared},
        )
        raw = await session.scalar(
            text("SELECT content->>'text' FROM public.messages WHERE id=:id"),
            {"id": assistant},
        )
    assert payload == expected
    assert raw == body  # Audit retains the original model output.
    assert (await service.send(prepared)).status == "ACCEPTED"
    assert provider.text_requests[0].body == expected
    assert await service.prepare_text(message_id=assistant) == prepared


async def test_pending_pre_release_payload_is_normalized_at_dispatch(session_factory):
    tenant, _, _, assistant = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.pending")]
    )
    service = OutboundMessageService(
        session_factory=session_factory, context=_context(tenant), provider=provider
    )
    prepared = await service.prepare_text(message_id=assistant)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.outbound_messages SET payload=:payload WHERE id=:id"
            ).bindparams(bindparam("payload", type_=JSONB)),
            {"id": prepared, "payload": {"body": "**Respuesta**"}},
        )
    assert (await service.send(prepared)).status == "ACCEPTED"
    assert provider.text_requests[0].body == "*Respuesta*"
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT payload->>'body' FROM public.outbound_messages WHERE id=:id"
                ),
                {"id": prepared},
            )
            == "*Respuesta*"
        )
