"""Unit tests for pure functional SDK specs, context, and registry (Zero Decorators)."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk.context import StitchContext
from ip.sdk.contracts import RequestSpec
from ip.sdk.registry import DomainFunctionKind, DomainFunctionRegistry
from ip.sdk.specs import (
    ConnectorSpec,
    MutationSpec,
    StitchSpec,
    TransformerSpec,
    retry_policy,
)


def test_connector_spec_registers_function() -> None:
    custom_registry = DomainFunctionRegistry()

    def fetch_contacts(cmd: object) -> RequestSpec:
        return RequestSpec(method="GET", path="/extract")

    spec = ConnectorSpec(
        app="source_crm",
        entity="contacts",
        fn=fetch_contacts,
        description="Extracts CRM contacts",
    )
    custom_registry.register_connector(spec)

    descriptor = custom_registry.get_connector("source_crm", "contacts")
    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.CONNECTOR
    assert descriptor.app == "source_crm"
    assert descriptor.entity == "contacts"
    assert descriptor.fn is fetch_contacts
    assert descriptor.description == "Extracts CRM contacts"


def test_transformer_spec_registers_function() -> None:
    custom_registry = DomainFunctionRegistry()

    def transform_contacts(raw: object) -> object:
        return {"status": "SUCCESS"}

    spec = TransformerSpec(
        app="source_crm",
        entity="contacts",
        fn=transform_contacts,
        description="Normalizes contacts",
    )
    custom_registry.register_transformer(spec)

    descriptor = custom_registry.get_transformer("source_crm", "contacts")
    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.TRANSFORMER
    assert descriptor.app == "source_crm"
    assert descriptor.entity == "contacts"
    assert descriptor.fn is transform_contacts
    assert descriptor.description == "Normalizes contacts"


def test_mutation_spec_registers_function() -> None:
    custom_registry = DomainFunctionRegistry()

    def upsert_asset(cmd: object) -> RequestSpec:
        return RequestSpec(method="PATCH", path="/assets/1")

    spec = MutationSpec(
        app="dest_erp",
        entity="assets",
        operation="UPSERT",
        fn=upsert_asset,
        description="Upserts ERP asset",
    )
    custom_registry.register_mutation(spec)

    descriptor = custom_registry.get_mutation("dest_erp", "assets", "UPSERT")
    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.MUTATION
    assert descriptor.app == "dest_erp"
    assert descriptor.entity == "assets"
    assert descriptor.operation == "UPSERT"
    assert descriptor.fn is upsert_asset
    assert descriptor.description == "Upserts ERP asset"


def test_stitch_spec_registers_function_with_sla_retry_configuration() -> None:
    custom_registry = DomainFunctionRegistry()

    async def execute_stitch(ctx: StitchContext, event: dict[str, str]) -> dict[str, str]:
        return {"status": "COMPLETED"}

    spec = StitchSpec(
        id="crm.request_account_data",
        trigger="crm.account_requested",
        handler=execute_stitch,
        name="Request Account Data",
        description="Fans out requests across 3 CRM systems",
        concurrency_key="account_serial_fifo",
        retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
        step_timeout=timedelta(minutes=5),
        workflow_sla=timedelta(hours=1),
    )
    custom_registry.register_stitch(spec)

    descriptor = custom_registry.get_stitch("crm.request_account_data")
    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.STITCH
    assert descriptor.stitch_id == "crm.request_account_data"
    assert descriptor.on_event == "crm.account_requested"
    assert descriptor.fn is execute_stitch
    assert descriptor.concurrency_key == "account_serial_fifo"
    assert descriptor.retry_policy is not None
    assert descriptor.retry_policy.max_attempts == 3
    assert descriptor.step_timeout == timedelta(minutes=5)
    assert descriptor.workflow_sla == timedelta(hours=1)
