from collections.abc import Iterable, Mapping

from agents_factory.modules.approvals.models import ApprovalError, ApprovalRouteDraft
from agents_factory.modules.capabilities.contracts import ActionDefinition
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY


def validate_route_action(route: ApprovalRouteDraft) -> None:
    definitions = [
        action
        for manifest in V1_CAPABILITY_REGISTRY.list()
        if manifest.stable_name == route.capability
        for action in manifest.actions
    ]
    if not any(action.name == route.action for action in definitions):
        raise ApprovalError("approval_route_action_unavailable")


def validate_required_routes(
    actions: Iterable[ActionDefinition], routes: Mapping[str, ApprovalRouteDraft]
) -> None:
    """Publication/composition gate for the permitted HIGH/approval-required actions."""
    for action in actions:
        if action.risk != "HIGH" and not action.requires_approval:
            continue
        route = routes.get(action.name)
        if route is None or not route.enabled or route.action != action.name:
            raise ApprovalError("approval_route_required")
        validate_route_action(route)
