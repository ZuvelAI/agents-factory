from typing import Any, cast

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database
from agents_factory.modules.cases.service import CaseService


async def configure_case_jobs(context: dict[Any, Any], *, database: Database) -> None:
    service = CaseService(database.session_factory)

    async def process_timer(envelope: JobEnvelope) -> None:
        if envelope.kind != "cases.timer":
            raise ValueError("invalid_case_timer")
        # The durable worker verifies tenant, topic and aggregate against outbox.
        await service.process_timer(
            context=TenantContext(
                envelope.tenant_id, envelope.job_id, "system", envelope.job_id
            ),
            case_id=envelope.aggregate_id,
        )

    cast(dict[str, JobHandler], context["job_handlers"])["cases.timer"] = process_timer
