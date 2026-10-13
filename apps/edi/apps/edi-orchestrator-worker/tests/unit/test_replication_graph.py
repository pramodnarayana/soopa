from dataclasses import dataclass
from typing import Any

import pytest
from edi.domain.replication import (
    EntityDependency,
    EntitySpec,
    topological_layers,
    validate_replication_graph,
)
from seedwork.domain.types import JsonDict


def _dummy_mapper(_entity: Any) -> JsonDict:
    return {"id": "dummy"}


@dataclass
class DummyControlPlaneModel:
    pass


@dataclass
class DummyDataPlaneModel:
    pass


class ControlPlaneA:
    pass


class DataPlaneA:
    pass


class ControlPlaneB:
    pass


class DataPlaneB:
    pass


class ControlPlaneC:
    pass


class DataPlaneC:
    pass


class ControlPlaneD:
    pass


class DataPlaneD:
    pass


def test_topological_layers_acyclic() -> None:
    """Test a normal acyclic dependency graph."""
    graph = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="a_id", target_key="A"),
            ],
        ),
        "C": EntitySpec(
            control_plane_model=ControlPlaneC,
            data_plane_model=DataPlaneC,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="b_id", target_key="B"),
                EntityDependency(fk_attr="a_id", target_key="A"),
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
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="a_id", target_key="A"),
            ],
        ),
        "C": EntitySpec(
            control_plane_model=ControlPlaneC,
            data_plane_model=DataPlaneC,
            mapper=_dummy_mapper,
        ),
        "D": EntitySpec(
            control_plane_model=ControlPlaneD,
            data_plane_model=DataPlaneD,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="c_id", target_key="C"),
            ],
        ),
    }

    layers = topological_layers(graph)

    # A and C have no dependencies
    assert layers[0] == ["A", "C"]
    # B and D depend on A and C respectively
    assert layers[1] == ["B", "D"]


def test_topological_layers_ignores_missing_dependencies() -> None:
    """If a dependency points to a key not in the graph, it's ignored for ordering."""
    graph = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="missing_id", target_key="MISSING"),
            ],
        )
    }

    layers = topological_layers(graph)
    assert layers == [["A"]]


def test_topological_layers_cyclic_raises_value_error() -> None:
    """Test that a circular dependency raises a ValueError."""
    graph = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="b_id", target_key="B"),
            ],
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="c_id", target_key="C"),
            ],
        ),
        "C": EntitySpec(
            control_plane_model=ControlPlaneC,
            data_plane_model=DataPlaneC,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="a_id", target_key="A"),
            ],
        ),
    }

    with pytest.raises(ValueError, match="Dependency cycle detected"):
        topological_layers(graph)


def test_validate_replication_graph_valid() -> None:
    """A valid, acyclic graph with all targets registered passes validation."""
    graph = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="a_id", target_key="A"),
            ],
        ),
    }
    # Should not raise
    validate_replication_graph(graph)


def test_validate_replication_graph_missing_target_raises_value_error() -> None:
    """An unregistered target_key raises a descriptive ValueError at startup."""
    graph = {
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="a_id", target_key="A"),
            ],
        ),
    }
    with pytest.raises(ValueError, match="pointing to unregistered target_key 'A'"):
        validate_replication_graph(graph)


def test_validate_replication_graph_self_dependency_raises_value_error() -> None:
    """A self-referential target_key raises a descriptive ValueError at startup."""
    graph = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
            dependencies=[
                EntityDependency(fk_attr="parent_a_id", target_key="A"),
            ],
        ),
    }
    with pytest.raises(
        ValueError, match="specifies self-dependency 'parent_a_id' pointing to itself"
    ):
        validate_replication_graph(graph)
