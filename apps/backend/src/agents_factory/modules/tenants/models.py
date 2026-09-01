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
    legal_name: str | None
    industry: str | None
    timezone: str | None
    locale: Literal["es-CO", "en-US"] | None
    status: TenantStatus
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(
        cls,
        *,
        slug: str,
        name: str,
        legal_name: str | None = None,
        industry: str | None = None,
        timezone: str | None = None,
        locale: Literal["es-CO", "en-US"] | None = None,
    ) -> Self:
        now = datetime.now(UTC)
        return cls(
            id=new_uuid7(),
            slug=slug,
            name=name,
            legal_name=legal_name,
            industry=industry,
            timezone=timezone,
            locale=locale,
            status="active",
            revision=1,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls(
            id=cast(UUID, row["id"]),
            slug=cast(str, row["slug"]),
            name=cast(str, row["name"]),
            legal_name=cast(str | None, row["legal_name"]),
            industry=cast(str | None, row["industry"]),
            timezone=cast(str | None, row["timezone"]),
            locale=cast(Literal["es-CO", "en-US"] | None, row["locale"]),
            status=cast(TenantStatus, row["status"]),
            revision=cast(int, row["revision"]),
            created_at=cast(datetime, row["created_at"]),
            updated_at=cast(datetime, row["updated_at"]),
        )
