from uuid import uuid4

from agents_factory.modules.privacy.minimization import (
    direct_identifier_free_metrics,
    pseudonymize,
)


def test_pseudonyms_are_tenant_bound_and_metrics_exclude_direct_ids() -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()

    assert pseudonymize(str(tenant_a), "customer") != pseudonymize(
        str(tenant_b), "customer"
    )
    assert pseudonymize(str(tenant_a), "customer").startswith("deleted:")
    assert not {"tenant_id", "conversation_id", "customer_ref"} & set(
        direct_identifier_free_metrics()
    )
