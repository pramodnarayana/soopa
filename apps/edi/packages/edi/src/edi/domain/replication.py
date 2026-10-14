"""
Declarative Replication Dependency Graph — Domain Types and Algorithms.

This module defines the pure domain types that model the FK dependency structure
between replicated entities, the topological sort algorithm that derives the
correct replication order from those types, and domain provisioning exceptions.

It is intentionally infrastructure-free. It contains no SQLAlchemy models,
no database connections, and no adapter concerns.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

ModelClass = type
MapperFunc = Callable[..., Mapping[str, object]]


class ProvisioningError(Exception):
    """Base exception for provisioning errors."""


class PermanentProvisioningError(ProvisioningError):
    """An error that cannot be resolved by retrying (e.g., bad payload)."""


class TransientProvisioningError(ProvisioningError):
    """An error that might be resolved by retrying (e.g., network failure)."""


@dataclass(frozen=True)
class EntityDependency:
    """
    Describes a single nullable FK field on an entity pointing to a replicated entity.

    Attributes:
        fk_attr:    The attribute name on the control-plane SQLAlchemy model that
                    holds the foreign key value (e.g. "as2_partner_id").
        target_key: The entity key in REPLICATION_GRAPH representing the dependency
                    (e.g. "as2_partner").
    """

    fk_attr: str
    target_key: str


@dataclass(frozen=True)
class EntitySpec:
    """
    Full replication specification for a single entity type.

    Attributes:
        control_plane_model: SQLAlchemy model class in the control-plane DB.
        data_plane_model:    SQLAlchemy model class in the data-plane shard DB.
        mapper:              Strictly-typed mapper function translating control-plane model to shard dict.
        include_shared:      If True, the query scope includes rows owned by
                             PLATFORM_TENANT_ID (shared platform configuration).
        dependencies:        Ordered list of FK dependencies that must be pre-replicated
                             before this entity can be safely upserted.
    """

    control_plane_model: ModelClass
    data_plane_model: ModelClass
    mapper: MapperFunc
    include_shared: bool = False
    dependencies: list[EntityDependency] = field(default_factory=list)


def topological_layers(graph: Mapping[str, EntitySpec]) -> list[list[str]]:
    """
    Compute the topological replication order of entities via Kahn's algorithm.

    Returns a list of layers. Each layer is a list of entity keys that have
    all their FK dependencies satisfied by earlier layers, and can therefore
    be safely replicated (or deleted in reverse) as a group.

    Raises:
        ValueError: If a dependency cycle is detected in the graph.
    """
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


def validate_replication_graph(graph: Mapping[str, EntitySpec]) -> None:
    """
    Strictly validates structural invariants of the replication graph:
    1. Every dependency target_key must be registered in the graph and cannot be a self-dependency.
    2. Every EntitySpec must have a callable mapper.
    3. The graph must be acyclic.
    """
    for entity_key, spec in graph.items():
        if not callable(spec.mapper):
            raise TypeError(
                f"EntitySpec '{entity_key}' has missing or non-callable mapper: {spec.mapper}"
            )
        for dep in spec.dependencies:
            if dep.target_key == entity_key:
                raise ValueError(
                    f"EntitySpec '{entity_key}' specifies self-dependency '{dep.fk_attr}' pointing to itself."
                )
            if dep.target_key not in graph:
                raise ValueError(
                    f"EntitySpec '{entity_key}' specifies dependency '{dep.fk_attr}' "
                    f"pointing to unregistered target_key '{dep.target_key}'. "
                    f"Registered entities: {sorted(graph.keys())}"
                )
    topological_layers(graph)
