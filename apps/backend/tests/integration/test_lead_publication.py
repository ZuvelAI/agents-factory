"""Old evidence remains readable but cannot approve new prospect behavior."""

from uuid import UUID

import pytest
from sqlalchemy import text

from agents_factory.common.errors import DomainError
from agents_factory.modules.agent_factory.publication_evidence import (
    PublicationEvidenceService,
    WorkspacePublicationEvidenceService,
)
from agents_factory.modules.agent_factory.publication_tests import run_candidate_tests
from agents_factory.modules.runtime.contracts import AgentTurnResult, RuntimeUsage
from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _configuration_client,
)
from apps.backend.tests.integration.test_workspace_publication_candidates import (
    ready_agent,
    prepare,
)
from apps.backend.tests.integration.test_workspace_publication_evidence import (
    request_run,
)
from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    context,
)

configuration_client = _configuration_client


async def test_legacy_suite_cannot_approve_new_capture_snapshot(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await ready_agent(client)
    config = draft["configuration"]
    config["lead_capture"] = {"enabled": True}
    saved = await client.put(
        root + f"/agents/{draft['agent_instance_id']}/configuration",
        json={"expected_revision": draft["revision"], "configuration": config},
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()
    candidate = await prepare(session_factory, draft)
    run = await request_run(session_factory, draft, candidate.version.id)
    frozen = candidate.version.compiled_spec
    legacy = frozen.model_copy(
        update={
            "configuration": frozen.configuration.model_copy(
                update={"capabilities": (), "permitted_tools": ()}
            )
        }
    )

    class Runtime:
        async def run(self, turn):
            return AgentTurnResult(
                "Respuesta para revisión", (), RuntimeUsage(1, 1, 0, 1, 0, 2), None
            )

    old_result = await run_candidate_tests(legacy, Runtime())
    assert old_result.checks_passed and len(old_result.scenarios) == 6
    actor = context(UUID(draft["tenant_id"]))
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await PublicationEvidenceService(
            session, actor, code_digest="a" * 64
        ).save_result(run.id, old_result)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = WorkspacePublicationEvidenceService(
            session, actor, code_digest="a" * 64
        )
        read = await service.read(UUID(draft["agent_instance_id"]), run.id)
        assert not read.is_current
        with pytest.raises(DomainError):
            await service.review(
                UUID(draft["agent_instance_id"]),
                run.id,
                expected_revision=draft["revision"],
                approved=True,
                confirm_review=True,
            )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.lead_prospects"))
            == 0
        )
