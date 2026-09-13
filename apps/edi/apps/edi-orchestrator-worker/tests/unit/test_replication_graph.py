from dataclasses import dataclass

import pytest

from worker.domain.replication_graph import EntityDependency, EntitySpec, topological_layers


@dataclass
class DummyGlobalModel:
    pass


@dataclass
class DummyTenantModel:
    pass


# A set of mock models to build our graph
class GlobalA:
    pass


class TenantA:
    pass


class GlobalB:
    pass


class TenantB:
    pass


class GlobalC:
    pass


class TenantC:
    pass


class GlobalD:
    pass


class TenantD:
    pass


def test_topological_layers_acyclic() -> None:
    """Test a normal acyclic dependency graph."""
    graph = {
        "A": EntitySpec(
            global_model=GlobalA,
            tenant_model=TenantA,
        ),
        "B": EntitySpec(
            global_model=GlobalB,
            tenant_model=TenantB,
            dependencies=[
                EntityDependency(fk_attr="a_id", global_model=GlobalA, tenant_model=TenantA)
            ],
        ),
        "C": EntitySpec(
            global_model=GlobalC,
            tenant_model=TenantC,
            dependencies=[
                EntityDependency(fk_attr="b_id", global_model=GlobalB, tenant_model=TenantB),
                EntityDependency(fk_attr="a_id", global_model=GlobalA, tenant_model=TenantA),
            ],
        ),
    }

    layers = topological_layers(graph)

    # A has no dependencies, it should be in the first layer
    assert layers[0] == ["A"]
    # B depends on A, so it should be in the second layer
    assert layers[1] == ["B"]
    # C depends on both A and B, so it's in the third layer
    assert layers[2] == ["C"]


def test_topological_layers_disconnected() -> None:
    """Test a graph with disconnected components."""
    graph = {
        "A": EntitySpec(
            global_model=GlobalA,
            tenant_model=TenantA,
        ),
        "B": EntitySpec(
            global_model=GlobalB,
            tenant_model=TenantB,
            dependencies=[
                EntityDependency(fk_attr="a_id", global_model=GlobalA, tenant_model=TenantA)
            ],
        ),
        "C": EntitySpec(
            global_model=GlobalC,
            tenant_model=TenantC,
        ),
        "D": EntitySpec(
            global_model=GlobalD,
            tenant_model=TenantD,
            dependencies=[
                EntityDependency(fk_attr="c_id", global_model=GlobalC, tenant_model=TenantC)
            ],
        ),
    }

    layers = topological_layers(graph)

    # A and C have no dependencies
    assert layers[0] == ["A", "C"]
    # B and D depend on A and C respectively
    assert layers[1] == ["B", "D"]


def test_topological_layers_ignores_missing_dependencies() -> None:
    """If a dependency points to a model not in the graph, it's ignored for ordering."""

    class GlobalMissing:
        pass

    class TenantMissing:
        pass

    graph = {
        "A": EntitySpec(
            global_model=GlobalA,
            tenant_model=TenantA,
            dependencies=[
                EntityDependency(
                    fk_attr="missing_id", global_model=GlobalMissing, tenant_model=TenantMissing
                )
            ],
        )
    }

    layers = topological_layers(graph)
    assert layers == [["A"]]


def test_topological_layers_cyclic_raises_value_error() -> None:
    """Test that a circular dependency raises a ValueError."""
    graph = {
        "A": EntitySpec(
            global_model=GlobalA,
            tenant_model=TenantA,
            dependencies=[
                EntityDependency(fk_attr="b_id", global_model=GlobalB, tenant_model=TenantB)
            ],
        ),
        "B": EntitySpec(
            global_model=GlobalB,
            tenant_model=TenantB,
            dependencies=[
                EntityDependency(fk_attr="c_id", global_model=GlobalC, tenant_model=TenantC)
            ],
        ),
        "C": EntitySpec(
            global_model=GlobalC,
            tenant_model=TenantC,
            dependencies=[
                EntityDependency(fk_attr="a_id", global_model=GlobalA, tenant_model=TenantA)
            ],
        ),
    }

    with pytest.raises(ValueError, match="Dependency cycle detected"):
        topological_layers(graph)
