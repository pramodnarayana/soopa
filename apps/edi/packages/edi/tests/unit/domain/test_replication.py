"""
Unit tests for declarative replication dependency graph and topological sorting.
"""

from collections.abc import Mapping

import pytest

from edi.domain.replication.graph import (
    EntityDependency,
    EntitySpec,
    EntitySpecProtocol,
    topological_layers,
    validate_replication_graph,
)


def _dummy_mapper(_entity: object) -> Mapping[str, object]:
    return {}


class ControlPlaneA:
    parent_a_id: str | None = None
    b_id: str | None = None


class DataPlaneA:
    pass


class ControlPlaneB:
    a_id: str | None = None


class DataPlaneB:
    pass


class ControlPlaneC:
    b_id: str | None = None


class DataPlaneC:
    pass


def test_topological_layers_acyclic() -> None:
    graph: dict[str, EntitySpecProtocol] = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=(
                EntityDependency(
                    fk_name="a_id",
                    fk_getter=lambda b: b.a_id,
                    target_key="A",
                ),
            ),
        ),
        "C": EntitySpec(
            control_plane_model=ControlPlaneC,
            data_plane_model=DataPlaneC,
            mapper=_dummy_mapper,
            dependencies=(
                EntityDependency(
                    fk_name="b_id",
                    fk_getter=lambda c: c.b_id,
                    target_key="B",
                ),
            ),
        ),
    }

    layers = topological_layers(graph)
    assert layers == [["A"], ["B"], ["C"]]


def test_topological_layers_cyclic_raises_value_error() -> None:
    graph: dict[str, EntitySpecProtocol] = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
            dependencies=(
                EntityDependency(
                    fk_name="b_id",
                    fk_getter=lambda a: a.b_id,
                    target_key="B",
                ),
            ),
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=(
                EntityDependency(
                    fk_name="a_id",
                    fk_getter=lambda b: b.a_id,
                    target_key="A",
                ),
            ),
        ),
    }

    with pytest.raises(ValueError, match="Dependency cycle detected"):
        topological_layers(graph)


def test_validate_replication_graph_valid() -> None:
    graph: dict[str, EntitySpecProtocol] = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
        ),
        "B": EntitySpec(
            control_plane_model=ControlPlaneB,
            data_plane_model=DataPlaneB,
            mapper=_dummy_mapper,
            dependencies=(
                EntityDependency(
                    fk_name="a_id",
                    fk_getter=lambda b: b.a_id,
                    target_key="A",
                ),
            ),
        ),
    }
    validate_replication_graph(graph)


def test_validate_replication_graph_self_dependency_raises_value_error() -> None:
    graph: dict[str, EntitySpecProtocol] = {
        "A": EntitySpec(
            control_plane_model=ControlPlaneA,
            data_plane_model=DataPlaneA,
            mapper=_dummy_mapper,
            dependencies=(
                EntityDependency(
                    fk_name="parent_a_id",
                    fk_getter=lambda a: a.parent_a_id,
                    target_key="A",
                ),
            ),
        ),
    }
    with pytest.raises(ValueError, match="specifies self-dependency"):
        validate_replication_graph(graph)
