import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from agents_factory.modules.approvals.models import ApprovalError, OTPInput
from agents_factory.modules.approvals.service import (
    ApprovalService,
    PersistedApprovalVerifier,
)
from apps.backend.tests.approval_support import ACTION, EMAILS, ApprovalHarness
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from scheduler.approval_jobs import configure_approval_jobs


async def test_first_response_is_atomic_and_execution_is_only_outboxed(
    order_world,  # noqa: F811
    caplog,
):
    world = order_world
    h = await ApprovalHarness.create(world)
    action, request = await h.request()
    assert (
        await h.service.request(context=world.context, action_id=action.id)
    ).id == request.id
    tokens = await h.notices(request)
    assert set(tokens) == set(EMAILS) and len(set(tokens.values())) == 2
    assert all(
        "Código de verificación:" not in mail.get_content() for mail in h.messages
    )
    await h.service.send_notices(context=world.context, request_id=request.id)
    assert len(h.messages) == 2
    commands = [
        await h.verification(tokens[email], email, outcome)
        for email, outcome in zip(EMAILS, ("APPROVE", "REJECT"))
    ]
    calls_before = sum(len(f.calls) for f in world.fixtures.values())
    results = await asyncio.gather(*(h.service.decide(command) for command in commands))
    assert sorted(r.status for r in results) == ["CLOSED", "RECORDED"]
    winner = commands[
        next(i for i, result in enumerate(results) if result.status == "RECORDED")
    ]
    async with h.service.transaction(world.context) as repo:
        persisted = await repo.request(request_id=request.id)
        decision = await repo.decision(request.id)
        links = await repo.links(request.id)
        jobs = (
            (
                await repo.session.execute(
                    text(
                        "SELECT topic,payload FROM public.outbox_jobs WHERE tenant_id=:tenant"
                    ),
                    {"tenant": world.context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        assert persisted.state == (
            "APPROVED" if winner.decision == "APPROVE" else "REJECTED"
        )
        assert (
            decision.approver_email == winner.email
            and decision.parameter_digest == action.parameter_digest
        )
        assert (
            decision.requested_result == winner.requested_result
            and decision.metadata == {}
        )
        assert all(link.invalidated_at and link.otp_digest is None for link in links)
        executions = [job for job in jobs if job.topic == "approvals.execute"]
        assert len(executions) == (1 if winner.decision == "APPROVE" else 0)
    assert sum(len(f.calls) for f in world.fixtures.values()) == calls_before
    for command in commands:
        assert (await h.service.decide(command)).status == "CLOSED"
    # A fresh service instance cannot reopen/replay consumed proofs.
    restarted = ApprovalService(
        world.sessions,
        proofs=h.service.proofs,
        mailer=h.service.mailer,
        public_origin=h.service.public_origin,
    )
    assert (await restarted.inspect(tokens[EMAILS[0]])).status == "CLOSED"
    assert all(link_value not in caplog.text for link_value in tokens.values())
    assert all(
        command.code.get_secret_value() not in caplog.text for command in commands
    )


async def test_otp_limits_expiry_revocation_and_uncertain_delivery(order_world):  # noqa: F811
    world = order_world
    h = await ApprovalHarness.create(
        world, expires_minutes=5, otp_seconds=30, otp_max_attempts=2
    )
    action, request = await h.request()
    tokens = await h.notices(request)
    link_value = tokens[EMAILS[0]]
    before = len(h.messages)
    await h.service.start_otp(
        OTPInput(link_token=link_value, email="intruder@example.test")
    )
    assert len(h.messages) == before
    command = await h.verification(link_value)
    original_challenge = command.challenge_id
    receipt = await h.service.start_otp(
        OTPInput(link_token=link_value, email=EMAILS[0])
    )
    assert receipt.challenge_id == original_challenge and len(h.messages) == before + 1
    async with h.service.transaction(world.context) as repo:
        links = await repo.links(request.id)
        link = next(link for link in links if link.email == EMAILS[0])
        assert link.otp_digest and link.otp_digest != command.code.get_secret_value()
        assert link_value not in link.model_dump_json()
    h.clock += timedelta(seconds=31)
    assert (await h.service.decide(command)).status == "INVALID_VERIFICATION"
    h.clock += timedelta(seconds=31)
    new_command = await h.verification(link_value)
    assert new_command.challenge_id != original_challenge
    assert (await h.service.decide(command)).status == "INVALID_VERIFICATION"
    assert (await h.service.decide(new_command)).status != "RECORDED"
    # Expiry closes every outstanding path without an execution job.
    h.clock = request.expires_at
    jobs = {"job_handlers": {}, "approval_service": h.service}
    assert "approvals.execute" not in configure_approval_jobs(jobs)
    await jobs["job_handlers"]["approvals.expire"](
        SimpleNamespace(
            kind="approvals.expire",
            tenant_id=world.context.tenant_id,
            job_id=uuid4(),
            aggregate_id=request.id,
        )
    )
    assert (
        await h.service.get(context=world.context, request_id=request.id)
    ).state == "EXPIRED"
    # Another request uses a separate durable delivery claim; unknown outcomes
    # must not trigger duplicate notices and cannot verify an OTP as delivered.
    h.clock -= timedelta(minutes=4)
    _, second = await h.request()
    h.uncertain = True
    second_tokens = await h.notices(second)
    count = len(h.messages)
    await h.service.send_notices(context=world.context, request_id=second.id)
    assert len(h.messages) == count
    uncertain_command = await h.verification(second_tokens[EMAILS[1]], EMAILS[1])
    assert (await h.service.decide(uncertain_command)).status == "INVALID_VERIFICATION"
    await h.service.save_route(
        context=world.context,
        configuration=h.configuration.model_copy(update={"enabled": False}),
        expected_revision=h.route.revision,
    )
    assert (await h.service.inspect(second_tokens[EMAILS[0]])).status == "CLOSED"
    async with h.service.transaction(world.context) as repo:
        assert (await repo.request(request_id=second.id)).state == "INVALIDATED"
        assert (
            await repo.session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='approvals.execute'"
                )
            )
            == 0
        )


async def test_approved_reference_is_bound_and_rejection_never_executes(order_world):  # noqa: F811
    world = order_world
    h = await ApprovalHarness.create(world)
    action, request = await h.request()
    tokens = await h.notices(request)
    command = await h.verification(tokens[EMAILS[0]])
    assert (await h.service.decide(command)).status == "RECORDED"
    async with h.service.transaction(world.context) as repo:
        decision = await repo.decision(request.id)
        payloads = (
            (
                await repo.session.execute(
                    text(
                        "SELECT payload FROM public.outbox_jobs WHERE topic='approvals.execute'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(payloads) == 1 and payloads[0]["approval_reference"] == str(
            decision.id
        )
        assert payloads[0]["parameter_digest"] == action.parameter_digest
        assert command.code.get_secret_value() not in json.dumps(payloads)
    verifier = PersistedApprovalVerifier(
        world.sessions, world.context, now=lambda: h.clock
    )
    args = dict(
        route_ref=h.configuration.ref,
        approval_reference=str(decision.id),
        action_id=action.id,
        parameter_digest=action.parameter_digest,
    )
    assert await verifier.verify(**args)
    for patch in (
        {"parameter_digest": "0" * 64},
        {"action_id": uuid4()},
        {"route_ref": "other"},
        {"approval_reference": str(uuid4())},
    ):
        assert not await verifier.verify(**{**args, **patch})
    other_action, other = await h.request()
    other_tokens = await h.notices(other)
    rejection = await h.verification(other_tokens[EMAILS[0]], decision="REJECT")
    assert (await h.service.decide(rejection)).status == "RECORDED"
    async with h.service.transaction(world.context) as repo:
        assert (await repo.request(request_id=other.id)).state == "REJECTED"
        assert (
            await repo.session.scalar(
                text("SELECT state FROM public.actions WHERE id=:id"),
                {"id": other_action.id},
            )
            == "REJECTED"
        )
        assert (
            await repo.session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='approvals.execute'"
                )
            )
            == 1
        )
    # Disabled routes immediately invalidate previously approved references.
    await h.service.save_route(
        context=world.context,
        configuration=h.configuration.model_copy(update={"enabled": False}),
        expected_revision=h.route.revision,
    )
    assert not await verifier.verify(**args)
    fresh = await world.request(
        next(iter(world.bindings)),
        ACTION,
        {"order_id": "42", "reason": "No enabled approval route"},
    )
    await world.confirm(fresh)
    with pytest.raises(ApprovalError, match="approval_route_required"):
        await h.service.request(context=world.context, action_id=fresh.id)
