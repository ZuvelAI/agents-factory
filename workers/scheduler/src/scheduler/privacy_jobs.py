from __future__ import annotations

from typing import Any, cast

from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database
from agents_factory.modules.privacy.deletion import PrivacyProcessor


def configure_privacy_jobs(context: dict[Any, Any], *, database: Database) -> None:
    processor = PrivacyProcessor(database.session_factory)

    async def process(envelope: JobEnvelope) -> None:
        if envelope.kind != "privacy.process":
            raise ValueError("invalid_privacy_job")
        await processor.process(
            tenant_id=envelope.tenant_id, job_id=envelope.aggregate_id
        )

    cast(dict[str, JobHandler], context["job_handlers"])["privacy.process"] = process
