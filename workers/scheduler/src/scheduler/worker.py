from __future__ import annotations

import os
from typing import Any, Mapping, cast

from arq import Retry
from arq.connections import ArqRedis, RedisSettings
from arq.cron import cron
from arq.typing import WorkerCoroutine

from agents_factory.common.queue import (
    OutboxDispatcher,
    close_durable_worker,
    configure_durable_worker,
    json_job_deserializer,
    json_job_serializer,
    run_registered_job,
)
from agents_factory.database import Database
from scheduler.knowledge_jobs import configure_knowledge_jobs


async def startup(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    redis = cast(ArqRedis, context["redis"])
    context["outbox_dispatcher"] = OutboxDispatcher(
        session_factory=database.session_factory,
        queue=redis,
        queue_by_kind={
            "whatsapp.inbound.received": "agent",
            "agent.turn": "agent",
            "outbound.text": "outbound",
            "whatsapp.outbound.send": "outbound",
            "knowledge.ingest": "knowledge",
            "knowledge.embed": "knowledge",
            "knowledge.detect_change": "scheduler",
        },
        retry_delay_seconds=1.0,
    )
    await configure_knowledge_jobs(context, database=database)


async def dispatch_outbox(context: dict[Any, Any]) -> dict[str, int]:
    dispatcher = cast(OutboxDispatcher, context["outbox_dispatcher"])
    result = await dispatcher.dispatch_once()
    return {
        "dispatched": result.dispatched,
        "already_enqueued": result.already_enqueued,
        "failed": result.failed,
    }


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
    cron_jobs = [
        cron(
            cast(WorkerCoroutine, dispatch_outbox),
            second=set(range(60)),
            run_at_startup=True,
        )
    ]
    queue_name = "scheduler"
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
    on_startup = startup
    on_shutdown = close_durable_worker
    job_serializer = json_job_serializer
    job_deserializer = json_job_deserializer
    max_tries = 100
    job_timeout = 300
    health_check_interval = 30
    health_check_key = "arq:health-check:scheduler"
