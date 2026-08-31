import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.usage.models import (
    CostQuote,
    UsageConfiguration,
    UsageEvent,
    UsageRecord,
)
from agents_factory.modules.usage.pricing import quote_usage


class UsageConflict(ValueError):
    pass


class UsageRecorder:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @asynccontextmanager
    async def transaction(
        self, context: TenantContext, *, admin: bool = False
    ) -> AsyncIterator[AsyncSession]:
        if context.actor_id is None or context.actor_type not in {
            "system",
            "platform_admin",
        }:
            raise UsageConflict("usage_backend_actor_required")
        if admin and context.actor_type != "platform_admin":
            raise UsageConflict("usage_admin_required")
        async with self.sessions.begin() as session:
            await session.execute(
                text(
                    "SET LOCAL ROLE agents_factory_admin"
                    if admin
                    else "SET LOCAL ROLE agents_factory_app"
                )
            )
            await set_tenant_context(session, context.tenant_id)
            yield session

    async def _configuration(
        self, session: AsyncSession, context: TenantContext
    ) -> tuple[UsageConfiguration, int]:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT configuration,revision FROM public.usage_configurations WHERE tenant_id=:tenant"
                    ),
                    {"tenant": context.tenant_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return (
            (UsageConfiguration(), 0)
            if row is None
            else (
                UsageConfiguration.model_validate(row["configuration"]),
                row["revision"],
            )
        )

    async def configuration(
        self, context: TenantContext
    ) -> tuple[UsageConfiguration, int]:
        async with self.transaction(context) as session:
            return await self._configuration(session, context)

    async def configure(
        self,
        *,
        context: TenantContext,
        configuration: UsageConfiguration,
        expected_revision: int,
    ) -> int:
        if expected_revision < 0:
            raise UsageConflict("invalid_usage_revision")
        async with self.transaction(context, admin=True) as session:
            lock = int.from_bytes(
                hashlib.sha256(f"usage-config:{context.tenant_id}".encode()).digest()[
                    :8
                ],
                "big",
                signed=True,
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock}
            )
            previous, revision = await self._configuration(session, context)
            if revision != expected_revision:
                raise UsageConflict("usage_configuration_conflict")
            next_prices = {p.id: p for p in configuration.prices}
            if any(next_prices.get(p.id) != p for p in previous.prices):
                raise UsageConflict("price_versions_are_immutable")
            await session.execute(
                text(
                    "INSERT INTO public.usage_configurations(id,tenant_id,configuration,revision) VALUES (:id,:tenant,CAST(:config AS jsonb),:revision) "
                    "ON CONFLICT(tenant_id) DO UPDATE SET configuration=excluded.configuration,revision=excluded.revision"
                ),
                {
                    "id": new_uuid7(),
                    "tenant": context.tenant_id,
                    "config": configuration.model_dump_json(),
                    "revision": revision + 1,
                },
            )
            await AuditService(session).record(
                context=context,
                event_type="usage.configured",
                entity_type="tenant",
                entity_id=context.tenant_id,
                payload={
                    "revision": revision + 1,
                    "price_versions": len(configuration.prices),
                },
            )
            return revision + 1

    async def record(self, *, context: TenantContext, event: UsageEvent) -> UsageRecord:
        serialized = json.dumps(
            event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        async with self.transaction(context) as session:
            existing = await self._existing(session, context, event.source_key)
            if existing is not None:
                return self._replay(existing, digest)
            # References are checked inside tenant scope before a write. No global
            # lookups and no raw provider response/customer content enter this ledger.
            for table, identifier in (
                ("conversations", event.conversation_id),
                ("actions", event.action_id),
                ("cases", event.case_id),
            ):
                if identifier is not None and not await session.scalar(
                    text(
                        f"SELECT EXISTS(SELECT 1 FROM public.{table} WHERE tenant_id=:tenant AND id=:id)"
                    ),
                    {"tenant": context.tenant_id, "id": identifier},
                ):
                    raise UsageConflict("usage_reference_unavailable")
            config, revision = await self._configuration(session, context)
            quote, price = quote_usage(event, config.prices)
            await session.execute(
                text(
                    "INSERT INTO public.usage_records(id,tenant_id,source_key,payload_digest,occurred_at,kind,provider,product,model,run_id,conversation_id,action_id,case_id,currency,cost_amount,event,quote,price_snapshot,configuration_revision) "
                    "VALUES (:id,:tenant,:key,:digest,:at,:kind,:provider,:product,:model,:run,:conversation,:action,:case,:currency,:amount,CAST(:event AS jsonb),CAST(:quote AS jsonb),CAST(:price AS jsonb),:revision) ON CONFLICT(tenant_id,source_key) DO NOTHING"
                ),
                {
                    "id": new_uuid7(),
                    "tenant": context.tenant_id,
                    "key": event.source_key,
                    "digest": digest,
                    "at": event.occurred_at,
                    "kind": event.kind,
                    "provider": event.provider,
                    "product": event.product,
                    "model": event.model,
                    "run": event.run_id,
                    "conversation": event.conversation_id,
                    "action": event.action_id,
                    "case": event.case_id,
                    "currency": event.currency,
                    "amount": quote.amount,
                    "event": serialized,
                    "quote": quote.model_dump_json(),
                    "price": None if price is None else price.model_dump_json(),
                    "revision": revision,
                },
            )
            saved = await self._existing(session, context, event.source_key)
            if saved is None:
                raise UsageConflict("usage_record_unavailable")
            return self._replay(saved, digest)

    async def _existing(
        self, session: AsyncSession, context: TenantContext, key: str
    ) -> RowMapping | None:
        return (
            (
                await session.execute(
                    text(
                        "SELECT id,tenant_id,payload_digest,event,quote,configuration_revision,recorded_at FROM public.usage_records WHERE tenant_id=:tenant AND source_key=:key"
                    ),
                    {"tenant": context.tenant_id, "key": key},
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _replay(row: RowMapping, digest: str) -> UsageRecord:
        if row["payload_digest"] != digest:
            raise UsageConflict("usage_idempotency_conflict")
        return UsageRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            event=UsageEvent.model_validate(row["event"]),
            quote=CostQuote.model_validate(row["quote"]),
            configuration_revision=row["configuration_revision"],
            recorded_at=row["recorded_at"],
        )
