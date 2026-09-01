from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.context import TenantContext
from agents_factory.modules.observability.dashboard import DashboardService
from agents_factory.modules.usage.models import Measurements, UsageEvent
from agents_factory.modules.usage.recorder import UsageRecorder


async def test_dashboard_preserves_attention_and_unknown_operational_evidence(
    session_factory,
):
    now = datetime.now(UTC)
    tenant_id = uuid4()
    agent_id = uuid4()
    integration_id = uuid4()
    job_id = uuid4()
    case_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name,status) "
                "VALUES (:id,:slug,'Dashboard Tenant','active')"
            ),
            {"id": tenant_id, "slug": f"dashboard-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_instances(id,tenant_id,product) "
                "VALUES (:id,:tenant,'Agent Customer Service')"
            ),
            {"id": agent_id, "tenant": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.integration_connections"
                "(id,tenant_id,connector_name,auth_kind,status,health_status) "
                "VALUES (:id,:tenant,'google_calendar','OAUTH2','PENDING','UNKNOWN')"
            ),
            {"id": integration_id, "tenant": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.outbox_jobs"
                "(id,tenant_id,idempotency_key,topic,payload,status,available_at) "
                "VALUES (:id,:tenant,'dashboard-job','agent.run','{}',"
                "'dead_letter',:at)"
            ),
            {"id": job_id, "tenant": tenant_id, "at": now},
        )
        await session.execute(
            text(
                "INSERT INTO public.dead_letter_jobs"
                "(id,tenant_id,outbox_job_id,reason_code,status) "
                "VALUES (:id,:tenant,:job,'fixture_failure','open')"
            ),
            {"id": uuid4(), "tenant": tenant_id, "job": job_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.cases"
                "(id,tenant_id,customer_ref,capability,issue_type,binding_id,"
                "resource_id,deduplication_key,content_digest,intake,revision,"
                "status,priority,policy,target_status,approaching_at,target_at,"
                "created_at,updated_at) VALUES "
                "(:id,:tenant,'opaque-customer','orders','delivery_issue',:binding,"
                "'opaque-order',:digest,:digest,:intake,1,'OPEN','CRITICAL',"
                ":policy,"
                "'OVERDUE',:approaching,:target,:created,:created)"
            ).bindparams(
                bindparam("intake", type_=JSONB),
                bindparam("policy", type_=JSONB),
            ),
            {
                "id": case_id,
                "tenant": tenant_id,
                "binding": uuid4(),
                "digest": "a" * 64,
                "intake": {},
                "policy": {
                    "close_after_hours": 72,
                    "target_minutes": {
                        "LOW": 2880,
                        "NORMAL": 1440,
                        "HIGH": 240,
                        "CRITICAL": 30,
                    },
                    "approaching_fraction": 0.8,
                    "priority_by_issue": {},
                },
                "approaching": now - timedelta(minutes=10),
                "target": now - timedelta(minutes=5),
                "created": now - timedelta(hours=1),
            },
        )

    context = TenantContext(tenant_id, uuid4(), "system", uuid4())
    await UsageRecorder(session_factory).record(
        context=context,
        event=UsageEvent(
            source_key="dashboard:usage:1",
            occurred_at=now,
            kind="llm",
            provider="fixture",
            product="fixture-model",
            model="fixture-model",
            currency="USD",
            measurements=Measurements(
                input_tokens=100,
                cached_input_tokens=0,
                output_tokens=50,
                requests=1,
            ),
        ),
    )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        summary = await DashboardService(session).summarize(
            now=now,
            service_checks={"database": "up", "redis": "down"},
        )

    assert summary.coverage.model_dump() == {
        "tenant_count": 1,
        "included_tenants": 1,
        "complete": True,
    }
    assert (summary.agents.configured, summary.agents.operating) == (1, 0)
    assert summary.operations.work_items_requiring_attention == 1
    assert summary.cases.critical_overdue == 1
    assert summary.integrations.state == "unknown"
    assert summary.integrations.unknown == 1
    assert summary.usage.model_tokens == 150
    assert summary.usage.unknown_cost_events == 1
    assert summary.usage.state == "unknown"
    assert summary.platform.state == "attention"
