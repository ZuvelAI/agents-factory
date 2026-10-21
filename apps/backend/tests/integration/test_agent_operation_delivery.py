import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.modules.whatsapp.outbound_service import OutboundMessageService
from agents_factory.modules.whatsapp.contracts import ProviderMessageResult
from apps.backend.tests.integration.test_outbound_idempotency import (
    _seed_text_reply,
    RecordingProvider,
)
from apps.backend.tests.integration.operation_fixtures import admit_fixture_message
from apps.backend.tests.integration.test_agent_message_admission import change_state


@pytest_asyncio.fixture
async def delivery_world(session_factory):
    tenant, account, conversation, assistant = await _seed_text_reply(session_factory)
    async with session_factory.begin() as session:
        incoming = await session.scalar(
            text("SELECT in_reply_to_message_id FROM public.messages WHERE id=:m"),
            {"m": assistant},
        )
        admission = await admit_fixture_message(session, incoming)
    admin = TenantContext(tenant, uuid4(), "platform_admin", uuid4())
    return (admin, account, admission.agent_instance_id), assistant


def service(factory, world, provider):
    return OutboundMessageService(
        session_factory=factory, context=world[0], provider=provider
    )


@pytest.mark.asyncio
async def test_prepared_reply_cannot_send_after_pause_or_resume(
    session_factory, delivery_world
):
    world, assistant = delivery_world
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="test.accepted")]
    )
    outbound = service(session_factory, world, provider)
    prepared = await outbound.prepare_text(message_id=assistant)
    await change_state(session_factory, world, False, 1)
    blocked = await outbound.send(prepared)
    assert (
        blocked.status == "BLOCKED"
        and blocked.error_code == "agent_operation_ineligible"
    )
    await change_state(session_factory, world, True, 2)
    assert (await outbound.send(prepared)).status == "BLOCKED"
    assert provider.text_requests == []


@pytest.mark.asyncio
async def test_automatic_reply_without_admission_is_blocked(session_factory):
    tenant, _, _, assistant = await _seed_text_reply(
        session_factory, operational_admission=False
    )
    world = (TenantContext(tenant, uuid4(), "platform_admin", uuid4()), None, None)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="not.allowed")]
    )
    outbound = service(session_factory, world, provider)
    result = await outbound.send(await outbound.prepare_text(message_id=assistant))
    assert (
        result.status == "BLOCKED" and result.error_code == "agent_operation_ineligible"
    )
    assert provider.text_requests == []


@pytest.mark.asyncio
async def test_pause_waits_for_delivery_already_started(
    session_factory, delivery_world
):
    world, assistant = delivery_world
    entered, release = asyncio.Event(), asyncio.Event()

    class Provider(RecordingProvider):
        async def send_text(self, request):
            entered.set()
            await release.wait()
            return await super().send_text(request)

    provider = Provider(
        [
            ProviderMessageResult(
                outcome="accepted", provider_message_id="started.before.pause"
            )
        ]
    )
    outbound = service(session_factory, world, provider)
    prepared = await outbound.prepare_text(message_id=assistant)
    sending = asyncio.create_task(outbound.send(prepared))
    pausing = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        pausing = asyncio.create_task(change_state(session_factory, world, False, 1))

        async def wait_blocked():
            while not pausing.done():
                async with session_factory.begin() as session:
                    if await session.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)"
                        )
                    ):
                        return
                await asyncio.sleep(0.01)
            raise AssertionError("pause confirmed while provider still running")

        await asyncio.wait_for(wait_blocked(), 3)
    finally:
        release.set()
        await asyncio.wait_for(sending, 3)
        if pausing is not None:
            await asyncio.wait_for(pausing, 3)
    assert len(provider.text_requests) == 1


@pytest.mark.asyncio
async def test_cancelled_delivery_releases_locks_and_keeps_uncertain_outcome(
    session_factory, delivery_world
):
    world, assistant = delivery_world
    entered = asyncio.Event()

    class Provider:
        async def send_text(self, request):
            entered.set()
            await asyncio.Event().wait()

        async def send_template(self, request):
            raise AssertionError("unexpected template")

    outbound = service(session_factory, world, Provider())
    prepared = await outbound.prepare_text(message_id=assistant)
    sending = asyncio.create_task(outbound.send(prepared))
    await asyncio.wait_for(entered.wait(), 3)
    sending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sending
    await asyncio.wait_for(change_state(session_factory, world, False, 1), 3)
    assert (await outbound.send(prepared)).status == "UNCERTAIN"


@pytest.mark.asyncio
async def test_http_failure_releases_locks_without_retrying(
    session_factory, delivery_world
):
    world, assistant = delivery_world

    class Provider:
        async def send_text(self, request):
            raise RuntimeError("synthetic failure")

        async def send_template(self, request):
            raise AssertionError("unexpected template")

    outbound = service(session_factory, world, Provider())
    prepared = await outbound.prepare_text(message_id=assistant)
    assert (await outbound.send(prepared)).status == "UNCERTAIN"
    await asyncio.wait_for(change_state(session_factory, world, False, 1), 3)
    assert (await outbound.send(prepared)).status == "UNCERTAIN"


@pytest.mark.asyncio
async def test_authority_read_failure_never_calls_provider(
    session_factory, delivery_world, monkeypatch
):
    from agents_factory.modules.agent_operations import delivery_guard

    world, assistant = delivery_world
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="forbidden")]
    )
    outbound = service(session_factory, world, provider)
    prepared = await outbound.prepare_text(message_id=assistant)

    async def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic authority read failure")

    monkeypatch.setattr(delivery_guard, "outbound_operation_allowed", unavailable)
    with pytest.raises(RuntimeError, match="authority read failure"):
        await outbound.send(prepared)
    assert not provider.text_requests
    await asyncio.wait_for(change_state(session_factory, world, False, 1), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
async def test_template_approval_does_not_grant_automatic_authority(
    session_factory, manual
):
    from apps.backend.tests.integration.test_template_policy import (
        _seed_account,
        _approved_template,
    )
    from agents_factory.modules.whatsapp.template_service import TemplateService

    tenant, account = await _seed_account(session_factory, label=str(uuid4()))
    preparing = TenantContext(
        tenant,
        uuid4() if manual else None,
        "platform_admin" if manual else "system",
        uuid4(),
    )
    templates = TemplateService(session_factory=session_factory, context=preparing)
    await templates.sync(whatsapp_account_id=account, templates=(_approved_template(),))
    prepared = await templates.prepare_proactive(
        whatsapp_account_id=account,
        recipient_wa_id="573001234567",
        template_name="appointment_confirmation",
        language="es_CO",
        variables={"customer_name": "Prueba", "appointment_time": "10:00"},
        idempotency_key=str(uuid4()),
    )

    class Provider:
        requests = []

        async def send_template(self, request):
            self.requests.append(request)
            return ProviderMessageResult(
                outcome="accepted", provider_message_id="manual.template"
            )

        async def send_text(self, request):
            raise AssertionError("unexpected text")

    provider = Provider()
    worker_context = TenantContext(tenant, None, "system", uuid4())
    result = await OutboundMessageService(
        session_factory=session_factory, context=worker_context, provider=provider
    ).send(prepared)
    assert result.status == ("ACCEPTED" if manual else "BLOCKED")
    assert len(provider.requests) == (1 if manual else 0)


@pytest.mark.asyncio
async def test_other_agent_can_pause_during_first_agents_delivery(
    session_factory, delivery_world
):
    world, assistant = delivery_world
    other_tenant, other_account, _, other_assistant = await _seed_text_reply(
        session_factory
    )
    async with session_factory.begin() as session:
        other_agent = await session.scalar(
            text(
                "SELECT agent_instance_id FROM public.account_agent_bindings WHERE whatsapp_account_id=:a"
            ),
            {"a": other_account},
        )
    other = (
        TenantContext(other_tenant, uuid4(), "platform_admin", uuid4()),
        other_account,
        other_agent,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    class Provider(RecordingProvider):
        async def send_text(self, request):
            entered.set()
            await release.wait()
            return await super().send_text(request)

    outbound = service(
        session_factory,
        world,
        Provider(
            [ProviderMessageResult(outcome="accepted", provider_message_id="isolated")]
        ),
    )
    sending = asyncio.create_task(
        outbound.send(await outbound.prepare_text(message_id=assistant))
    )
    try:
        await asyncio.wait_for(entered.wait(), 3)
        paused = await asyncio.wait_for(
            change_state(session_factory, other, False, 1), 3
        )
        assert paused.enabled is False
    finally:
        release.set()
        await asyncio.wait_for(sending, 3)
