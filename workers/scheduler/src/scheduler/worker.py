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
from scheduler.appointment_jobs import configure_appointment_jobs
from scheduler.case_jobs import configure_case_jobs
from scheduler.approval_jobs import configure_approval_jobs
from scheduler.lifecycle_jobs import configure_lifecycle_jobs
from scheduler.lifecycle_scan import LifecycleScanner
from scheduler.retention_jobs import configure_retention_jobs
from scheduler.usage_jobs import configure_usage_jobs, record_storage_usage


async def startup(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    redis = cast(ArqRedis, context["redis"])
    retention_enabled = configure_retention_jobs(context, database=database)
    context["lifecycle_scanner"] = LifecycleScanner(
        database.session_factory, retention_enabled=retention_enabled
    )
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
            "appointments.notify": "scheduler",
            "cases.timer": "scheduler",
            **configure_approval_jobs(context),
            "approvals.expire": "scheduler",
            "actions.expire": "scheduler",
            "handoffs.inactivity": "scheduler",
            **({"retention.cleanup": "scheduler"} if retention_enabled else {}),
        },
        retry_delay_seconds=1.0,
    )
    await configure_knowledge_jobs(context, database=database)
    await configure_appointment_jobs(context, database=database)
    await configure_case_jobs(context, database=database)
    configure_lifecycle_jobs(context, database=database)
    configure_usage_jobs(context, database=database)


async def scan_lifecycles(context: dict[Any, Any]) -> dict[str, int]:
    scanner = cast(LifecycleScanner, context["lifecycle_scanner"])
    tenants = await scanner.tenants(after=context.get("lifecycle_scan_cursor"))
    created, failures = 0, 0
    for tenant_id in tenants:
        try:
            created += await scanner.scan_tenant(tenant_id)
        except Exception:
            # One bad tenant must not prevent other tenants' expiry/cleanup.
            # No content or exception text is included in scheduler telemetry.
            failures += 1
    context["lifecycle_scan_cursor"] = tenants[-1] if tenants else None
    return {"tenants": len(tenants), "scheduled": created, "failed_tenants": failures}


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
        cron(cast(WorkerCoroutine, scan_lifecycles), second=0, run_at_startup=True),
        cron(
            cast(WorkerCoroutine, dispatch_outbox),
            second=set(range(60)),
            run_at_startup=True,
        ),
        cron(
            cast(WorkerCoroutine, record_storage_usage),
            second=30,
            run_at_startup=True,
        ),
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
