from agents_factory.modules.capabilities.orders.manifest import action_gate
from agents_factory.modules.capabilities.orders.issues import missing_information
from agents_factory.modules.capabilities.orders.models import IssueDraft
from evals.case_schema import OrderProbe


def observe_order(probe: OrderProbe) -> str:
    if probe.issue is not None and missing_information(
        IssueDraft.model_validate(probe.issue)
    ):
        return "NEEDS_INFORMATION"
    return action_gate(
        probe.operation,
        identity_level=probe.identity_level,
        confirmed=probe.confirmed,
        approved=probe.approved,
        supported=probe.supported,
    )
