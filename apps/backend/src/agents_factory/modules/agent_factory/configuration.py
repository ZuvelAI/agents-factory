from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.agent_factory.models import (
    AgentSpecConfiguration,
    AgentSpecVersion,
    ConnectorBinding,
    HumanOperationsConfiguration,
    VersionReference,
)
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.schemas import (
    ApprovalRoutesDraftRequest,
    CapabilityDraftUpdateRequest,
    ConnectorBindingDraftRequest,
    HumanOperationsDraftRequest,
    PolicyDraftUpdateRequest,
)
from agents_factory.modules.capabilities.registry import (
    ManifestNotFound,
    V1_CAPABILITY_REGISTRY,
)
from agents_factory.modules.identity.models import IdentityLevel
from agents_factory.modules.integrations.registry import (
    ConnectorManifestNotFound,
    V1_CONNECTOR_CATALOG,
)
from agents_factory.modules.policies.evaluator import (
    ActionPolicyEvaluator,
    WeakenedSafetyPolicy,
)
from agents_factory.modules.policies.models import TenantActionPolicy


class AgentConfigurationService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._repository = AgentSpecRepository(session, context)

    async def update_capabilities(
        self,
        *,
        agent_instance_id: UUID,
        request: CapabilityDraftUpdateRequest,
    ) -> AgentSpecVersion:
        base = await self._base(agent_instance_id, request.expected_version_id)
        if len(set(request.capability_names)) != len(request.capability_names):
            raise _configuration_error("capabilities_duplicate")
        try:
            manifests = tuple(
                V1_CAPABILITY_REGISTRY.get(name, "1.0.0")
                for name in request.capability_names
            )
        except ManifestNotFound:
            raise _configuration_error("capability_unavailable") from None
        enabled_actions = tuple(
            sorted(action.name for manifest in manifests for action in manifest.actions)
        )
        enabled_set = set(enabled_actions)
        configuration = base.configuration.model_copy(
            update={
                "capabilities": tuple(
                    VersionReference(name=item.stable_name, version=item.version)
                    for item in manifests
                ),
                "permitted_tools": enabled_actions,
                "permitted_actions": enabled_actions,
                "action_policies": tuple(
                    policy
                    for policy in base.configuration.action_policies
                    if policy.action in enabled_set
                ),
            }
        )
        return await self._save(agent_instance_id, base, configuration)

    async def update_policies(
        self,
        *,
        agent_instance_id: UUID,
        request: PolicyDraftUpdateRequest,
    ) -> AgentSpecVersion:
        base = await self._base(agent_instance_id, request.expected_version_id)
        definitions = {
            action.name: action
            for reference in base.configuration.capabilities
            for action in V1_CAPABILITY_REGISTRY.get(
                reference.name, reference.version
            ).actions
        }
        evaluator = ActionPolicyEvaluator()
        try:
            for policy in request.policies:
                definition = definitions.get(policy.action)
                if definition is None or policy.action not in set(
                    base.configuration.permitted_actions
                ):
                    raise _configuration_error("policy_action_unavailable")
                if (
                    policy.identity_level < definition.required_identity_level
                    or definition.requires_confirmation
                    and not policy.confirmation_required
                    or definition.requires_approval
                    and not policy.approval_required
                ):
                    raise _configuration_error("policy_weakens_platform_minimum")
                evaluator.evaluate(
                    risk=definition.risk,
                    minimum_identity_level=IdentityLevel(
                        definition.required_identity_level
                    ),
                    tenant_policy=TenantActionPolicy(
                        identity_level=IdentityLevel(policy.identity_level),
                        confirmation_required=policy.confirmation_required,
                        approval_required=policy.approval_required,
                    ),
                )
        except WeakenedSafetyPolicy:
            raise _configuration_error("policy_weakens_platform_minimum") from None
        next_version = str(base.version_number + 1)
        configuration = base.configuration.model_copy(
            update={
                "action_policies": tuple(request.policies),
                "policy": VersionReference(
                    name="tenant_action_policy", version=next_version
                ),
                "identity_policy": VersionReference(
                    name="tenant_identity_policy", version=next_version
                ),
            }
        )
        return await self._save(agent_instance_id, base, configuration)

    async def bind_connector(
        self,
        *,
        agent_instance_id: UUID,
        request: ConnectorBindingDraftRequest,
    ) -> AgentSpecVersion:
        base = await self._base(agent_instance_id, request.expected_version_id)
        if len(set(request.operations)) != len(request.operations):
            raise _configuration_error("connector_operations_duplicate")
        connection = (
            (
                await self._session.execute(
                    text(
                        "SELECT connector_name,status FROM public.integration_connections "
                        "WHERE tenant_id=:tenant AND id=:connection"
                    ),
                    {
                        "tenant": base.tenant_id,
                        "connection": request.connection_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            connection is None
            or connection["connector_name"] != request.connector_name
            or connection["status"] != "CONNECTED"
        ):
            raise _configuration_error("connector_binding_unavailable")
        try:
            manifest = V1_CONNECTOR_CATALOG.get(request.connector_name, "1.0.0")
        except ConnectorManifestNotFound:
            raise _configuration_error("connector_unavailable") from None
        if manifest.availability != "AVAILABLE" or not set(request.operations).issubset(
            manifest.supported_operations
        ):
            raise _configuration_error("connector_operation_unsupported")
        binding = ConnectorBinding(
            binding_id=request.connection_id,
            connector=request.connector_name,
            connector_version=manifest.version,
            operations=tuple(sorted(request.operations)),
        )
        bindings = tuple(
            item
            for item in base.configuration.connector_bindings
            if item.binding_id != request.connection_id
        ) + (binding,)
        configuration = base.configuration.model_copy(
            update={"connector_bindings": bindings}
        )
        return await self._save(agent_instance_id, base, configuration)

    async def update_human_operations(
        self,
        *,
        agent_instance_id: UUID,
        request: HumanOperationsDraftRequest,
    ) -> AgentSpecVersion:
        base = await self._base(agent_instance_id, request.expected_version_id)
        handoff_surface_available = False
        if request.handoff_enabled:
            handoff_surface_available = (
                await self._session.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM public.handoff_configurations "
                        "WHERE tenant_id=:tenant "
                        "AND configuration->>'enabled'='true' "
                        "AND configuration->'surface' IS NOT NULL)"
                    ),
                    {"tenant": base.tenant_id},
                )
            ) is True
        if request.handoff_enabled and not handoff_surface_available:
            raise _configuration_error("human_surface_required")
        configuration = base.configuration.model_copy(
            update={
                "human_operations": HumanOperationsConfiguration(
                    version=str(base.version_number + 1),
                    handoff_enabled=request.handoff_enabled,
                    handoff_surface_available=handoff_surface_available,
                    awaiting_human_policy=(
                        base.configuration.human_operations.awaiting_human_policy
                    ),
                )
            }
        )
        return await self._save(agent_instance_id, base, configuration)

    async def update_approval_routes(
        self,
        *,
        agent_instance_id: UUID,
        request: ApprovalRoutesDraftRequest,
    ) -> AgentSpecVersion:
        base = await self._base(agent_instance_id, request.expected_version_id)
        configuration = base.configuration.model_copy(
            update={
                "approval_routes": VersionReference(
                    name="standard", version=str(request.route_revision)
                )
            }
        )
        return await self._save(agent_instance_id, base, configuration)

    async def _base(
        self, agent_instance_id: UUID, expected_version_id: UUID
    ) -> AgentSpecVersion:
        instance = await self._repository.get_instance(agent_instance_id)
        base = await self._repository.get_version(expected_version_id)
        if (
            instance is None
            or base is None
            or base.agent_instance_id != agent_instance_id
        ):
            raise _configuration_error("agent_spec_not_found", status=404)
        return base

    async def _save(
        self,
        agent_instance_id: UUID,
        base: AgentSpecVersion,
        configuration: AgentSpecConfiguration,
    ) -> AgentSpecVersion:
        created = await self._repository.create_draft_from_latest(
            agent_instance_id=agent_instance_id,
            expected_latest_version_id=base.id,
            configuration=configuration,
        )
        if created is None:
            raise _configuration_error("agent_spec_stale_write")
        return created


def _configuration_error(code: str, *, status: int = 409) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/agent-configuration",
        title="Agent Configuration Unavailable",
        status=status,
        detail="The requested Agent Draft configuration could not be applied.",
        code=code,
    )
