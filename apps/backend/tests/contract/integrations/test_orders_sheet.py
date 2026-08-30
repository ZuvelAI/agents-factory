from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from apps.backend.tests.order_support import SheetFixture, CUSTOMER, ADDRESS, WooFixture
from apps.backend.tests.contract.integrations.google.test_google_contracts import (
    request,
)
from agents_factory.modules.integrations.orders import (
    READS,
    WRITES,
    configured_order_binding,
)
from agents_factory.modules.integrations.google.auth import SHEETS_READ
from agents_factory.modules.integrations.google.orders_sheet import OrdersSheetResource


async def test_sheets_read_parity_sparse_pagination_and_duplicate_mapping() -> None:
    sheet, woo = SheetFixture(max_rows=600), WooFixture()
    sheet.rows[521] = sheet.rows.pop(2)
    for operation in READS:
        args = {"customer": CUSTOMER, "order_id": "42"}
        left = await sheet.adapter.execute(request(sheet.binding, operation, args))
        right = await woo.adapter.execute(request(woo.binding, operation, args))
        assert left.status == right.status == "SUCCEEDED"

        def without_version(data):
            return {
                key: [without_version(item) for item in value]
                if key == "orders"
                else value
                for key, value in data.items()
                if key != "version"
            }

        assert without_version(left.data) == without_version(right.data)
    page = await sheet.adapter.execute(
        request(sheet.binding, READS[0], {"customer": CUSTOMER, "limit": 1})
    )
    assert page.data == {"orders": [], "next_page": 2}
    denied = await sheet.adapter.execute(
        request(
            sheet.binding,
            READS[1],
            {"customer": {"customer_id": "9"}, "order_id": "42"},
        )
    )
    assert denied.error_code == "order_not_found" and not denied.data
    sheet.rows[522] = sheet.rows[521].copy()
    duplicate = await sheet.adapter.execute(
        request(sheet.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
    )
    assert duplicate.error_code == "ambiguous_order_mapping"


async def test_sheets_all_writes_replay_cell_preservation_and_shipped_cancellation() -> (
    None
):
    fixture = SheetFixture()
    for operation, changes in zip(
        WRITES,
        (
            {"address": ADDRESS},
            {"contact": {"phone": "+571111111111"}},
            {"note": "=not a formula"},
            {"reason": "Customer request"},
        ),
    ):
        read = await fixture.adapter.execute(
            request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
        )
        command = request(
            fixture.binding,
            operation,
            {
                "customer": CUSTOMER,
                "order_id": "42",
                "expected_version": read.data["version"],
                **changes,
            },
            key=operation,
        )
        result = await fixture.adapter.execute(command)
        assert result.status == "SUCCEEDED", result
        replay = await fixture.adapter.execute(command)
        assert replay.data["replayed"] is True
    assert fixture.writes == 4 and fixture.rows[2][2] == "processing"
    assert result.data["cancellation_executed"] is False
    fixture.rows[2][2] = "shipped"
    read = await fixture.adapter.execute(
        request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
    )
    denied = await fixture.adapter.execute(
        request(
            fixture.binding,
            WRITES[3],
            {
                "customer": CUSTOMER,
                "order_id": "42",
                "expected_version": read.data["version"],
                "reason": "Late",
            },
            key="late",
        )
    )
    assert denied.error_code == "order_not_mutable"


async def test_sheets_mapping_scope_conflicts_and_ambiguous_write() -> None:
    fixture = SheetFixture()
    read = await fixture.adapter.execute(
        request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
    )
    args = {
        "customer": CUSTOMER,
        "order_id": "42",
        "expected_version": read.data["version"],
        "address": ADDRESS,
    }
    fixture.conflict = True
    denied = await fixture.adapter.execute(request(fixture.binding, WRITES[0], args))
    assert denied.error_code == "stale_version" and fixture.writes == 0
    fixture.conflict = False
    fixture.rows[2][2] = "processing"
    fixture.fail_write = True
    uncertain = await fixture.adapter.execute(request(fixture.binding, WRITES[0], args))
    assert uncertain.status == "UNCERTAIN"
    fixture.bad_headers = True
    mismatch = await fixture.adapter.execute(
        request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
    )
    assert mismatch.error_code == "header_mapping_mismatch"
    readonly = SheetFixture(scopes=(SHEETS_READ,))
    scope = await readonly.adapter.execute(request(readonly.binding, WRITES[0], args))
    assert scope.error_code == "insufficient_scope" and readonly.writes == 0
    with pytest.raises(ValidationError):
        OrdersSheetResource.model_validate(
            {
                **fixture.resource.model_dump(),
                "fields": {"order_id": "order_id", "status": "order_id"},
            }
        )


async def test_readonly_sheet_and_partial_bindings_cannot_publish_or_execute_writes() -> (
    None
):
    from agents_factory.modules.capabilities.registry import CapabilityRegistry
    from agents_factory.modules.capabilities.service import (
        CapabilityService,
        AgentSpecManifestError,
    )
    from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG
    from apps.backend.tests.unit.integrations.test_operation_gating import (
        spec,
        orders_capability,
        action,
    )

    fixture = SheetFixture(writable=False)
    bound = configured_order_binding(
        binding_id=fixture.binding.binding_id,
        connector="google_sheets",
        resource=fixture.resource,
        allow_writes=True,
    )
    assert not set(bound.operations).intersection(WRITES)
    declared = orders_capability().model_copy(
        update={
            "actions": tuple(
                action(op, "LOW" if op in READS else "MEDIUM")
                for op in (*READS, *WRITES)
            )
        }
    )
    service = CapabilityService(
        capabilities=CapabilityRegistry((declared,)),
        connectors=V1_CONNECTOR_CATALOG,
    )
    original = spec(bound_operations=("orders.get_status",))
    configured = original.model_copy(
        update={
            "configuration": original.configuration.model_copy(
                update={"connector_bindings": (bound,), "permitted_actions": ()}
            )
        }
    )
    service.validate_agent_spec(configured)
    forbidden = configured.model_copy(
        update={
            "configuration": configured.configuration.model_copy(
                update={"permitted_actions": (WRITES[0],)}
            )
        }
    )
    with pytest.raises(AgentSpecManifestError):
        service.validate_agent_spec(forbidden)
    # Even a forged runtime binding cannot widen the actual resource mapping.
    fixture.adapter.binding = replace(fixture.binding, operations=frozenset(WRITES))
    denied = await fixture.adapter.execute(request(fixture.binding, WRITES[0], {}))
    assert denied.error_code == "operation_not_allowed" and not fixture.calls
    partial = fixture.resource.model_copy(
        update={
            "writable_fields": frozenset({"contact_information", "action_receipts"})
        }
    )
    assert set(partial.supported_operations).intersection(WRITES) == {WRITES[1]}
