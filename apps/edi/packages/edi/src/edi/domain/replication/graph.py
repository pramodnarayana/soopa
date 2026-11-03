"""Declarative Replication Dependency Graph — Domain Types and Algorithms.

This module defines the pure domain types that model the FK dependency structure
between replicated entities, the topological sort algorithm that derives the
correct replication order from those types, and domain provisioning exceptions.

It is intentionally infrastructure-free. It contains no SQLAlchemy models,
no database connections, and no adapter concerns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

TSource = TypeVar("TSource")


class ProvisioningError(Exception):
    """Base exception for provisioning errors."""


class PermanentProvisioningError(ProvisioningError):
    """An error that cannot be resolved by retrying (e.g., bad payload)."""


class TransientProvisioningError(ProvisioningError):
    """An error that might be resolved by retrying (e.g., network failure)."""


class EntityDependencyProtocol(Protocol):
    """Read-only structural protocol for a declared FK dependency."""

    @property
    def fk_name(self) -> str: ...

    @property
    def target_key(self) -> str: ...


@dataclass(frozen=True)
class EntityDependency(Generic[TSource]):
    """Describes a single nullable FK field on an entity pointing to a replicated entity."""

    fk_name: str
    fk_getter: Callable[[TSource], str | None]
    target_key: str


class EntitySpecProtocol(Protocol):
    """Read-only structural protocol allowing heterogeneous EntitySpec[TSource] registries."""

    @property
    def control_plane_model(self) -> type: ...

    @property
    def data_plane_model(self) -> type: ...

    @property
    def include_shared(self) -> bool: ...

    @property
    def dependencies(self) -> Sequence[EntityDependencyProtocol]: ...

    def map_entity(self, entity: object) -> Mapping[str, object]: ...

    def resolve_dependency_fk(self, entity: object, dep_index: int) -> str | None: ...


@dataclass(frozen=True)
class EntitySpec(Generic[TSource]):
    """Full strongly-typed replication specification for a single entity type."""

    control_plane_model: type[TSource]
    data_plane_model: type
    mapper: Callable[[TSource], Mapping[str, object]]
    include_shared: bool = False
    dependencies: Sequence[EntityDependency[TSource]] = field(default_factory=tuple)

    def map_entity(self, entity: object) -> Mapping[str, object]:
        if not isinstance(entity, self.control_plane_model):
            raise TypeError(
                f"Expected {self.control_plane_model.__name__}, got {type(entity).__name__}"
            )
        return self.mapper(entity)

    def resolve_dependency_fk(self, entity: object, dep_index: int) -> str | None:
        if not isinstance(entity, self.control_plane_model):
            raise TypeError(
                f"Expected {self.control_plane_model.__name__}, got {type(entity).__name__}"
            )
        return self.dependencies[dep_index].fk_getter(entity)


def topological_layers(graph: Mapping[str, EntitySpecProtocol]) -> list[list[str]]:
    """Compute the topological replication order of entities via Kahn's algorithm."""
    deps_by_key: dict[str, set[str]] = {}
    for key, spec in graph.items():
        dep_keys: set[str] = set()
        for dep in spec.dependencies:
            if dep.target_key in graph:
                dep_keys.add(dep.target_key)
        deps_by_key[key] = dep_keys

    layers: list[list[str]] = []
    remaining: set[str] = set(graph.keys())
    resolved: set[str] = set()

    while remaining:
        ready: set[str] = {k for k in remaining if deps_by_key[k].issubset(resolved)}

        if not ready:
            raise ValueError(
                f"Dependency cycle detected in REPLICATION_GRAPH. "
                f"Unresolvable entities: {sorted(remaining)}."
            )

        layers.append(sorted(ready))
        resolved |= ready
        remaining -= ready

    return layers


def validate_replication_graph(graph: Mapping[str, EntitySpecProtocol]) -> None:
    """Strictly validates structural invariants of the replication graph."""
    for entity_key, spec in graph.items():
        for dep in spec.dependencies:
            if dep.target_key == entity_key:
                raise ValueError(
                    f"EntitySpec '{entity_key}' specifies self-dependency '{dep.fk_name}' pointing to itself."
                )
            if dep.target_key not in graph:
                raise ValueError(
                    f"EntitySpec '{entity_key}' has dependency '{dep.fk_name}' pointing to unregistered target_key '{dep.target_key}'."
                )
    topological_layers(graph)
