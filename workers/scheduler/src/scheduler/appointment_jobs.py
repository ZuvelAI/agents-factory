from __future__ import annotations

from typing import Any, cast

from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database
from agents_factory.modules.capabilities.appointments.communications import (
    prepare_appointment_notification,
)


async def configure_appointment_jobs(
    context: dict[Any, Any], *, database: Database
) -> None:
    async def notify(envelope: JobEnvelope) -> None:
        await prepare_appointment_notification(
            sessions=database.session_factory, envelope=envelope
        )

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["appointments.notify"] = notify
