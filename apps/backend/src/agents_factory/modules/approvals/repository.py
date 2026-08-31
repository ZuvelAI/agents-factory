from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.modules.approvals.models import (
    ApprovalDecision,
    ApprovalLink,
    ApprovalRequest,
    ApprovalRoute,
)


class ApprovalRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def route(
        self,
        *,
        route_id: UUID | None = None,
        ref: str = "",
        capability: str = "",
        action: str = "",
        lock: str = "",
    ) -> ApprovalRoute | None:
        if lock not in {"", " FOR UPDATE", " FOR SHARE"}:
            raise ValueError("invalid route lock")
        predicate = (
            "id=:id"
            if route_id is not None
            else "ref=:ref AND capability=:capability AND action=:action"
        )
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT id,tenant_id,revision,configuration,digest FROM public.approval_routes WHERE tenant_id=:tenant AND "
                        + predicate
                        + lock
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "id": route_id,
                        "ref": ref,
                        "capability": capability,
                        "action": action,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return ApprovalRoute.model_validate(dict(row)) if row is not None else None

    async def save_route(self, route: ApprovalRoute, *, new: bool) -> None:
        values = {
            "id": route.id,
            "tenant": self.context.tenant_id,
            "ref": route.configuration.ref,
            "capability": route.configuration.capability,
            "action": route.configuration.action,
            "revision": route.revision,
            "configuration": route.configuration.model_dump(mode="json"),
            "digest": route.digest,
        }
        sql = (
            "INSERT INTO public.approval_routes(id,tenant_id,ref,capability,action,revision,configuration,digest) VALUES (:id,:tenant,:ref,:capability,:action,:revision,:configuration,:digest)"
            if new
            else "UPDATE public.approval_routes SET revision=:revision,configuration=:configuration,digest=:digest WHERE tenant_id=:tenant AND id=:id"
        )
        await self.session.execute(
            text(sql).bindparams(bindparam("configuration", type_=JSONB)), values
        )

    async def request(
        self,
        *,
        request_id: UUID | None = None,
        action_id: UUID | None = None,
        locked: bool = False,
    ) -> ApprovalRequest | None:
        predicate = "id=:id" if request_id is not None else "action_id=:action"
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.approval_requests WHERE tenant_id=:tenant AND "
                        + predicate
                        + (" FOR UPDATE" if locked else "")
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "id": request_id,
                        "action": action_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return ApprovalRequest.model_validate(dict(row)) if row is not None else None

    async def insert_request(self, request: ApprovalRequest) -> None:
        fields = tuple(ApprovalRequest.model_fields)
        await self.session.execute(
            text(
                f"INSERT INTO public.approval_requests({','.join(fields)}) VALUES ({','.join(':' + field for field in fields)})"
            ),
            request.model_dump(),
        )

    async def links(self, request_id: UUID) -> tuple[ApprovalLink, ...]:
        rows = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.approval_links WHERE tenant_id=:tenant AND request_id=:request ORDER BY id"
                    ),
                    {"tenant": self.context.tenant_id, "request": request_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(ApprovalLink.model_validate(dict(row)) for row in rows)

    async def link(self, request_id: UUID, link_id: UUID) -> ApprovalLink | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.approval_links WHERE tenant_id=:tenant AND request_id=:request AND id=:id"
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "request": request_id,
                        "id": link_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return ApprovalLink.model_validate(dict(row)) if row is not None else None

    async def save_link(self, link: ApprovalLink, *, new: bool = False) -> None:
        fields = tuple(ApprovalLink.model_fields)
        if new:
            sql = f"INSERT INTO public.approval_links({','.join(fields)}) VALUES ({','.join(':' + field for field in fields)})"
        else:
            mutable = [
                field
                for field in fields
                if field
                not in {"id", "tenant_id", "request_id", "email", "token_digest"}
            ]
            sql = (
                "UPDATE public.approval_links SET "
                + ",".join(f"{field}=:{field}" for field in mutable)
                + " WHERE tenant_id=:tenant_id AND id=:id AND request_id=:request_id"
            )
        await self.session.execute(text(sql), link.model_dump())

    async def insert_decision(self, decision: ApprovalDecision) -> None:
        values = decision.model_dump()
        values["requested_result"] = decision.requested_result.model_dump(mode="json")
        fields = tuple(ApprovalDecision.model_fields)
        await self.session.execute(
            text(
                f"INSERT INTO public.approval_decisions({','.join(fields)}) VALUES ({','.join(':' + field for field in fields)})"
            ).bindparams(
                bindparam("requested_result", type_=JSONB),
                bindparam("metadata", type_=JSONB),
            ),
            values,
        )

    async def decision(self, request_id: UUID) -> ApprovalDecision | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.approval_decisions WHERE tenant_id=:tenant AND request_id=:request"
                    ),
                    {"tenant": self.context.tenant_id, "request": request_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return ApprovalDecision.model_validate(dict(row)) if row is not None else None
