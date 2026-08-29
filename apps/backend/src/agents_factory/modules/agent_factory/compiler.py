from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from agents_factory.modules.agent_factory.models import (
    AgentSpec,
    AgentSpecDraft,
    ConnectorBinding,
)


@dataclass(frozen=True, slots=True)
class CanonicalDocument:
    json: str
    digest: str


@dataclass(frozen=True, slots=True)
class CompiledAgentSpec:
    spec: AgentSpec
    canonical_json: str
    digest: str


class AgentSpecDraftSource(Protocol):
    async def get_draft(
        self, *, agent_instance_id: UUID, draft_version_id: UUID
    ) -> AgentSpecDraft | None: ...


class AgentSpecValidator(Protocol):
    def validate_agent_spec(self, spec: AgentSpec) -> None: ...


class AgentSpecDraftNotFound(LookupError):
    pass


def canonical_json(value: BaseModel) -> CanonicalDocument:
    encoded = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return CanonicalDocument(
        json=encoded,
        digest=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


class AgentSpecCompiler:
    def __init__(
        self,
        drafts: AgentSpecDraftSource,
        *,
        validator: AgentSpecValidator | None = None,
    ) -> None:
        self._drafts = drafts
        self._validator = validator

    async def compile(
        self, agent_instance_id: UUID, draft_version_id: UUID
    ) -> CompiledAgentSpec:
        draft = await self._drafts.get_draft(
            agent_instance_id=agent_instance_id,
            draft_version_id=draft_version_id,
        )
        if draft is None:
            raise AgentSpecDraftNotFound
        configuration = draft.configuration.model_copy(
            update={
                "capabilities": tuple(
                    sorted(
                        draft.configuration.capabilities,
                        key=lambda item: (item.name, item.version),
                    )
                ),
                "permitted_tools": tuple(sorted(draft.configuration.permitted_tools)),
                "permitted_actions": tuple(
                    sorted(draft.configuration.permitted_actions)
                ),
                "connector_bindings": tuple(
                    _sorted_binding(binding)
                    for binding in sorted(
                        draft.configuration.connector_bindings,
                        key=lambda item: (
                            item.connector,
                            item.connector_version,
                            str(item.binding_id),
                        ),
                    )
                ),
            }
        )
        spec = AgentSpec(
            tenant_id=draft.tenant_id,
            agent_instance_id=draft.agent_instance_id,
            version_id=draft.id,
            version_number=draft.version_number,
            configuration=configuration,
        )
        if self._validator is not None:
            self._validator.validate_agent_spec(spec)
        document = canonical_json(spec)
        return CompiledAgentSpec(
            spec=spec,
            canonical_json=document.json,
            digest=document.digest,
        )


def _sorted_binding(binding: ConnectorBinding) -> ConnectorBinding:
    return binding.model_copy(update={"operations": tuple(sorted(binding.operations))})
