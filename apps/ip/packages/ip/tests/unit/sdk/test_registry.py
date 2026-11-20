"""Unit tests for SDK in-memory function registry."""

from ip.sdk.contracts import RequestSpec
from ip.sdk.registry import DomainFunctionKind, DomainFunctionRegistry


def test_registry_stores_connector_descriptor() -> None:
    registry = DomainFunctionRegistry()

    def dummy_connector(payload: object) -> RequestSpec:
        return RequestSpec(method="GET", path="/test")

    registry.register_connector(app="source_system", entity="records", fn=dummy_connector)
    descriptor = registry.get_connector(app="source_system", entity="records")

    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.CONNECTOR
    assert descriptor.app == "source_system"
    assert descriptor.entity == "records"
    assert descriptor.fn is dummy_connector


def test_registry_stores_transformer_descriptor() -> None:
    registry = DomainFunctionRegistry()

    def dummy_transformer(raw: object) -> object:
        return {"normalized": True}

    registry.register_transformer(app="source_system", entity="records", fn=dummy_transformer)
    descriptor = registry.get_transformer(app="source_system", entity="records")

    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.TRANSFORMER
    assert descriptor.fn is dummy_transformer


def test_registry_stores_mutation_descriptor() -> None:
    registry = DomainFunctionRegistry()

    def dummy_mutation(cmd: object) -> RequestSpec:
        return RequestSpec(method="POST", path="/orders")

    registry.register_mutation(
        app="erp_system", entity="orders", operation="CREATE", fn=dummy_mutation
    )
    descriptor = registry.get_mutation(app="erp_system", entity="orders", operation="CREATE")

    assert descriptor is not None
    assert descriptor.kind == DomainFunctionKind.MUTATION
    assert descriptor.operation == "CREATE"
    assert descriptor.fn is dummy_mutation


def test_registry_clears_stored_descriptors() -> None:
    registry = DomainFunctionRegistry()
    registry.register_connector("app", "entity", lambda _: RequestSpec(method="GET", path="/"))
    assert registry.get_connector("app", "entity") is not None

    registry.clear()
    assert registry.get_connector("app", "entity") is None
