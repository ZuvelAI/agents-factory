import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contracts import WhatsAppHistorySync
from agents_factory.modules.whatsapp.history_sync import persist_history
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping
from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor


async def test_history_is_durable_deduplicated_and_queues_only_archive_import(
    session_factory,
):
    tenant, account = uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'History test')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','history-waba','history-phone','active','COEXISTENCE','ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "history-phone"},
        "history": [
            {
                "metadata": {"phase": 2, "chunk_order": 1, "progress": 100},
                "threads": [
                    {
                        "id": "573000000001",
                        "messages": [
                            {
                                "from": "573000000001",
                                "id": "old",
                                "timestamp": "1739230970",
                                "type": "text",
                                "text": {"body": "Old question"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "history-waba",
                    "changes": [{"field": "history", "value": value}],
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(b"test-only", body, hashlib.sha256).hexdigest()
    for _ in range(2):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(app_secret=SecretStr("test-only")),
            ).process(raw_body=body, signature=signature, correlation_id=uuid4())
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT whatsapp_account_id,payload FROM public.whatsapp_history_inbox"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1
        assert rows[0]["whatsapp_account_id"] == account
        assert rows[0]["payload"]["chunks"] == value["history"]
        for table in ("messages", "conversations"):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
        jobs = (
            (
                await session.execute(
                    text("SELECT topic,payload FROM public.outbox_jobs")
                )
            )
            .mappings()
            .all()
        )
        assert len(jobs) == 1
        assert jobs[0]["topic"] == "whatsapp.history.import"
        assert jobs[0]["payload"]["aggregate_id"] == str(
            await session.scalar(text("SELECT id FROM public.whatsapp_history_inbox"))
        )
        await set_tenant_context(session, uuid4())
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_inbox")
            )
            == 0
        )


@pytest.mark.parametrize("invalid", ["mode", "phone", "waba", "tenant"])
async def test_history_rejects_invalid_account_scope(session_factory, invalid):
    tenant, account = uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'History test')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','waba','phone','active',:mode,'ELIGIBLE')"
            ),
            {
                "id": account,
                "tenant": tenant,
                "mode": "API_ONLY" if invalid == "mode" else "COEXISTENCE",
            },
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        with pytest.raises(DomainError) as error:
            await persist_history(
                session,
                context=TenantContext(
                    tenant_id=tenant,
                    actor_id=None,
                    actor_type="system",
                    correlation_id=uuid4(),
                ),
                mapping=WhatsAppAccountMapping(
                    account_id=account,
                    tenant_id=uuid4() if invalid == "tenant" else tenant,
                ),
                event=WhatsAppHistorySync(
                    waba_id="wrong" if invalid == "waba" else "waba",
                    phone_number_id="wrong" if invalid == "phone" else "phone",
                    chunks=(),
                    media_messages=(),
                ),
            )
        assert error.value.code == "history_sync_account_invalid"
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_inbox")
            )
            == 0
        )
