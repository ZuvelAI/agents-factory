from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agents_factory.common.queue import JobEnvelope
from agents_factory.modules.secrets.contracts import SecretAccessDenied
from agents_factory.modules.secrets.repository import SecretVault
from outbound_worker.jobs import _context


def envelope() -> JobEnvelope:
    return JobEnvelope(
        job_id=uuid4(), tenant_id=uuid4(), kind="whatsapp.outbound.send",
        aggregate_id=uuid4(),
    )


def test_service_identity_is_stable_and_tenant_scoped() -> None:
    job = envelope()
    context = _context(job)
    assert context.actor_id is not None
    assert context.actor_type == "system"
    assert context.tenant_id == job.tenant_id
    assert context.correlation_id == job.job_id
    assert _context(replace(job, job_id=uuid4())).actor_id == context.actor_id
    assert _context(replace(job, tenant_id=uuid4())).actor_id != context.actor_id


@pytest.mark.asyncio
async def test_vault_identity_gate_accepts_worker_but_still_denies_anonymous() -> None:
    vault = object.__new__(SecretVault)
    vault._denial_audit = AsyncMock()
    context = _context(envelope())
    assert await vault._require_context(context, operation="load") == context
    with pytest.raises(SecretAccessDenied):
        await vault._require_context(replace(context, actor_id=None), operation="load")
    vault._denial_audit.record.assert_awaited_once()
