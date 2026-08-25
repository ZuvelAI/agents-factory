from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self, cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from agents_factory.common.ids import new_uuid7


TenantStatus = Literal["active", "suspended"]


@dataclass(frozen=True, slots=True)
class Tenant:
    id: UUID
    slug: str
    name: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, *, slug: str, name: str) -> Self:
        now = datetime.now(UTC)
        return cls(
            id=new_uuid7(),
            slug=slug,
            name=name,
            status="active",
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls(
            id=cast(UUID, row["id"]),
            slug=cast(str, row["slug"]),
            name=cast(str, row["name"]),
            status=cast(TenantStatus, row["status"]),
            created_at=cast(datetime, row["created_at"]),
            updated_at=cast(datetime, row["updated_at"]),
        )
