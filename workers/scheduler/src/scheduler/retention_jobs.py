from typing import Any, cast

from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.observability.retention import RetentionService


def configure_retention_jobs(context: dict[Any, Any], *, database: Database) -> bool:
    service = context.get("retention_service")
    if not isinstance(service, RetentionService):
        return False

    async def process(envelope: JobEnvelope) -> None:
        if (
            envelope.kind != "retention.cleanup"
            or envelope.aggregate_id != envelope.tenant_id
        ):
            raise ValueError("invalid_retention_job")
        async with database.session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await set_tenant_context(session, envelope.tenant_id)
            payload = await session.scalar(
                text(
                    "SELECT payload FROM public.outbox_jobs WHERE tenant_id=:tenant AND id=:id AND topic='retention.cleanup' AND available_at<=:now"
                ),
                {
                    "tenant": envelope.tenant_id,
                    "id": envelope.job_id,
                    "now": service.now(),
                },
            )
            if not isinstance(payload, dict) or payload.get("aggregate_id") != str(
                envelope.tenant_id
            ):
                raise ValueError("retention_job_binding_mismatch")
        await service.run(
            context=TenantContext(
                envelope.tenant_id, envelope.job_id, "system", envelope.job_id
            )
        )

    cast(dict[str, JobHandler], context["job_handlers"])["retention.cleanup"] = process
    return True
