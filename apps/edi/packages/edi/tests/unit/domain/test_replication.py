"""
Unit tests for declarative replication dependency graph and topological sorting.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest

from edi.domain.replication import (
    EntityDependency,
    EntitySpec,
    topological_layers,
    validate_replication_graph,
)


def _dummy_mapper(_entity: Any) -> Mapping[str, object]:
    return {}


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


def test_topological_layers_acyclic() -> None:
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
            ],
        ),
    }

    layers = topological_layers(graph)
    assert layers == [["A"], ["B"], ["C"]]


def test_topological_layers_cyclic_raises_value_error() -> None:
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
                EntityDependency(fk_attr="a_id", target_key="A"),
            ],
        ),
    }

    with pytest.raises(ValueError, match="Dependency cycle detected"):
        topological_layers(graph)


def test_validate_replication_graph_valid() -> None:
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
    validate_replication_graph(graph)


def test_validate_replication_graph_self_dependency_raises_value_error() -> None:
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
    with pytest.raises(ValueError, match="specifies self-dependency"):
        validate_replication_graph(graph)
