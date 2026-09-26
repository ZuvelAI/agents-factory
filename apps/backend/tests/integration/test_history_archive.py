import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.common.queue import JobEnvelope
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp import history_sync
from agent_worker.jobs import handle_whatsapp_history_import


async def _enqueue_archive_job(session_factory, tenant, account, inbox):
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        job = await OutboxService(session).enqueue(
            context=TenantContext(
                tenant_id=tenant,
                actor_id=None,
                actor_type="system",
                correlation_id=uuid4(),
            ),
            idempotency_key=f"whatsapp.history.import:{inbox}",
            topic="whatsapp.history.import",
            payload={
                "aggregate_id": str(inbox),
                "inbox_id": str(inbox),
                "whatsapp_account_id": str(account),
            },
        )
    return JobEnvelope(
        job_id=job.id,
        tenant_id=tenant,
        kind="whatsapp.history.import",
        aggregate_id=inbox,
    )


async def test_archive_worker_imports_without_starting_live_conversations(
    session_factory,
):
    tenant, account, inbox = uuid4(), uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'Archive worker')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','worker-waba','worker-phone','active','COEXISTENCE','ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_history_inbox (id,tenant_id,whatsapp_account_id,payload_digest,payload) VALUES (:id,:tenant,:account,repeat('a',64),CAST(:payload AS jsonb))"
            ),
            {
                "id": inbox,
                "tenant": tenant,
                "account": account,
                "payload": json.dumps(
                    {
                        "chunks": [
                            {
                                "metadata": {
                                    "phase": 0,
                                    "chunk_order": 1,
                                    "progress": 100,
                                },
                                "threads": [
                                    {
                                        "id": "573000000001",
                                        "messages": [
                                            {
                                                "id": "worker-old",
                                                "from": "573000000001",
                                                "timestamp": "1739230970",
                                                "type": "text",
                                                "text": {"body": "Old question"},
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                        "media_messages": [],
                    }
                ),
            },
        )
    envelope = await _enqueue_archive_job(session_factory, tenant, account, inbox)
    database = SimpleNamespace(session_factory=session_factory)
    await handle_whatsapp_history_import(envelope=envelope, database=database)
    await handle_whatsapp_history_import(envelope=envelope, database=database)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_messages")
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_import_receipts")
            )
            == 1
        )
        for table in ("messages", "conversations"):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
        assert (
            await session.scalar(text("SELECT topic FROM public.outbox_jobs"))
        ) == "whatsapp.history.import"


async def test_archive_worker_reconciles_media_that_arrived_before_chunk(
    session_factory,
):
    tenant, account, media_inbox, chunk_inbox = uuid4(), uuid4(), uuid4(), uuid4()
    media = {
        "chunks": [],
        "media_messages": [
            {
                "id": "worker-media",
                "from": "business",
                "timestamp": "1739230970",
                "type": "image",
                "image": {"id": "asset-123"},
            }
        ],
    }
    chunk = {
        "chunks": [
            {
                "metadata": {"phase": 0, "chunk_order": 1, "progress": 100},
                "threads": [
                    {
                        "id": "573000000001",
                        "messages": [
                            {
                                "id": "worker-media",
                                "from": "business",
                                "timestamp": "1739230970",
                                "type": "media_placeholder",
                            }
                        ],
                    }
                ],
            }
        ],
        "media_messages": [],
    }
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'Archive delayed media')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','worker-media-waba','worker-media-phone','active','COEXISTENCE','ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        for inbox, digest, payload in (
            (media_inbox, "b" * 64, media),
            (chunk_inbox, "c" * 64, chunk),
        ):
            await session.execute(
                text(
                    "INSERT INTO public.whatsapp_history_inbox (id,tenant_id,whatsapp_account_id,payload_digest,payload) VALUES (:id,:tenant,:account,:digest,CAST(:payload AS jsonb))"
                ),
                {
                    "id": inbox,
                    "tenant": tenant,
                    "account": account,
                    "digest": digest,
                    "payload": json.dumps(payload),
                },
            )
    database = SimpleNamespace(session_factory=session_factory)
    media_job = await _enqueue_archive_job(
        session_factory, tenant, account, media_inbox
    )
    chunk_job = await _enqueue_archive_job(
        session_factory, tenant, account, chunk_inbox
    )
    await handle_whatsapp_history_import(envelope=media_job, database=database)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_import_receipts")
            )
            == 0
        )
    await handle_whatsapp_history_import(envelope=chunk_job, database=database)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        content = await session.scalar(
            text(
                "SELECT content FROM public.whatsapp_history_messages WHERE provider_message_id='worker-media'"
            )
        )
        assert content["type"] == "image"
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_import_receipts")
            )
            == 2
        )
        for table in ("messages", "conversations"):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )


async def test_archived_history_is_idempotent_tenant_scoped_and_silent(session_factory):
    tenant, account, inbox = uuid4(), uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'History archive')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','archive-waba','archive-phone','active','COEXISTENCE','ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_history_inbox (id,tenant_id,whatsapp_account_id,payload_digest,payload) VALUES (:id,:tenant,:account,repeat('c',64),CAST(:payload AS jsonb))"
            ),
            {
                "id": inbox,
                "tenant": tenant,
                "account": account,
                "payload": '{"chunks":[{"metadata":{"phase":0,"chunk_order":1,"progress":55},"threads":[{"id":"573000000001","messages":[{"id":"old-one","from":"573000000001","timestamp":"1739230970","type":"text","text":{"body":"Old question"}}]}]}],"media_messages":[]}',
            },
        )
    context = TenantContext(
        tenant_id=tenant, actor_id=None, actor_type="system", correlation_id=uuid4()
    )
    for expected in (1, 0):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            assert (
                await history_sync.import_history_inbox(
                    session, context=context, inbox_id=inbox
                )
                == expected
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT provider_message_id,customer_wa_id,direction,content FROM public.whatsapp_history_messages"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1
        assert (
            rows[0]["provider_message_id"],
            rows[0]["customer_wa_id"],
            rows[0]["direction"],
        ) == ("old-one", "573000000001", "inbound")
        assert rows[0]["content"]["text"]["body"] == "Old question"
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_import_receipts")
            )
            == 1
        )
        for table in ("messages", "conversations", "outbox_jobs"):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
        await set_tenant_context(session, uuid4())
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_messages")
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_import_receipts")
            )
            == 0
        )


async def test_delayed_media_fills_archived_placeholder_without_live_side_effects(
    session_factory,
):
    tenant, account, chunk_inbox, media_inbox = uuid4(), uuid4(), uuid4(), uuid4()
    placeholder = {
        "chunks": [
            {
                "metadata": {"phase": 0, "chunk_order": 1, "progress": 55},
                "threads": [
                    {
                        "id": "573000000001",
                        "messages": [
                            {
                                "id": "old-media",
                                "from": "business",
                                "timestamp": "1739230970",
                                "type": "media_placeholder",
                            }
                        ],
                    }
                ],
            }
        ],
        "media_messages": [],
    }
    media = {
        "chunks": [],
        "media_messages": [
            {
                "id": "old-media",
                "from": "business",
                "timestamp": "1739230970",
                "type": "image",
                "image": {"id": "asset-123"},
            }
        ],
    }
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'Media test')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','media-waba','media-phone','active','COEXISTENCE','ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        for inbox, digest, payload in (
            (chunk_inbox, "e" * 64, placeholder),
            (media_inbox, "f" * 64, media),
        ):
            await session.execute(
                text(
                    "INSERT INTO public.whatsapp_history_inbox (id,tenant_id,whatsapp_account_id,payload_digest,payload) VALUES (:id,:tenant,:account,:digest,CAST(:payload AS jsonb))"
                ),
                {
                    "id": inbox,
                    "tenant": tenant,
                    "account": account,
                    "digest": digest,
                    "payload": json.dumps(payload),
                },
            )
    context = TenantContext(
        tenant_id=tenant, actor_id=None, actor_type="system", correlation_id=uuid4()
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        assert (
            await history_sync.import_history_inbox(
                session, context=context, inbox_id=media_inbox
            )
            == 0
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        assert (
            await history_sync.import_history_inbox(
                session, context=context, inbox_id=chunk_inbox
            )
            == 1
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        assert (
            await history_sync.import_history_inbox(
                session, context=context, inbox_id=media_inbox
            )
            == 0
        )
        await set_tenant_context(session, tenant)
        content = await session.scalar(
            text(
                "SELECT content FROM public.whatsapp_history_messages WHERE provider_message_id='old-media'"
            )
        )
        assert content["type"] == "image"
        assert content["image"] == {"id": "asset-123"}
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_import_receipts")
            )
            == 2
        )
        for table in ("messages", "conversations", "outbox_jobs"):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                text(
                    "UPDATE public.whatsapp_history_messages SET content=CAST(:content AS jsonb) WHERE provider_message_id='old-media'"
                ),
                {
                    "content": json.dumps(
                        {
                            "id": "old-media",
                            "type": "image",
                            "image": {"id": "different"},
                        }
                    )
                },
            )
        assert error.value.orig.sqlstate == "23514"


async def test_archive_cannot_import_another_tenants_inbox(session_factory):
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        context = TenantContext(
            tenant_id=uuid4(),
            actor_id=None,
            actor_type="system",
            correlation_id=uuid4(),
        )
        with pytest.raises(ValueError, match="History inbox not found"):
            await history_sync.import_history_inbox(
                session, context=context, inbox_id=uuid4()
            )


@pytest.mark.parametrize(
    "payload,outcome",
    [
        (
            {"chunks": [{"errors": [{"code": 2593109}]}], "media_messages": []},
            "DECLINED",
        ),
        (
            {
                "chunks": [],
                "media_messages": [
                    {
                        "id": "late",
                        "from": "business",
                        "timestamp": "1739230970",
                        "type": "image",
                        "image": {"id": "asset"},
                    }
                ],
            },
            None,
        ),
    ],
)
async def test_archive_records_denial_but_does_not_claim_unmatched_media(
    session_factory, payload, outcome
):
    tenant, account, inbox = uuid4(), uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'History status')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility) VALUES (:id,:tenant,'meta','status-waba','status-phone','active','COEXISTENCE','ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_history_inbox (id,tenant_id,whatsapp_account_id,payload_digest,payload) VALUES (:id,:tenant,:account,repeat('d',64),CAST(:payload AS jsonb))"
            ),
            {
                "id": inbox,
                "tenant": tenant,
                "account": account,
                "payload": json.dumps(payload),
            },
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        context = TenantContext(
            tenant_id=tenant, actor_id=None, actor_type="system", correlation_id=uuid4()
        )
        if outcome is None:
            assert (
                await history_sync.import_history_inbox(
                    session, context=context, inbox_id=inbox
                )
                == 0
            )
        else:
            assert (
                await history_sync.import_history_inbox(
                    session, context=context, inbox_id=inbox
                )
                == 0
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        receipts = (
            (
                await session.execute(
                    text(
                        "SELECT outcome,errors FROM public.whatsapp_history_import_receipts"
                    )
                )
            )
            .mappings()
            .all()
        )
        if outcome is None:
            assert receipts == []
        else:
            assert receipts[0]["outcome"] == "DECLINED"
            assert receipts[0]["errors"] == [{"code": 2593109}]
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_history_messages")
            )
            == 0
        )
