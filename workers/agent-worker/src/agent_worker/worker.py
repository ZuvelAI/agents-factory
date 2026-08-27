from __future__ import annotations

import os
from typing import Any, Mapping

from arq import Retry
from arq.connections import RedisSettings

from agents_factory.common.queue import (
    close_durable_worker,
    configure_durable_worker,
    json_job_deserializer,
    json_job_serializer,
    run_registered_job,
)


async def process_job(
    context: dict[Any, Any],
    payload: Mapping[str, object],
) -> str:
    result = await run_registered_job(context, payload)
    if result.status == "retry":
        raise Retry(defer=1)
    return result.status


class WorkerSettings:
    functions = [process_job]
    queue_name = "agent"
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
    on_startup = configure_durable_worker
    on_shutdown = close_durable_worker
    job_serializer = json_job_serializer
    job_deserializer = json_job_deserializer
    max_tries = 100
    job_timeout = 300
    health_check_interval = 30
    health_check_key = "arq:health-check:agent"
