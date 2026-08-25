"""
Declarative Replication Dependency Graph — Domain Types and Algorithms.

This module defines the pure domain types that model the FK dependency structure
between replicated entities, and the topological sort algorithm that derives the
correct replication order from those types.

It is intentionally infrastructure-free. It contains no SQLAlchemy models,
no database connections, and no adapter concerns.

Architecture:
    - `EntityDependency` describes a single nullable FK field on an entity.
    - `EntitySpec` describes a full entity: its global/tenant model pair,
      tenant-scoping semantics, and the list of FK dependencies it carries.
    - `topological_layers` computes the safe replication order from any
      dict of EntitySpec values via Kahn's algorithm.

The concrete `REPLICATION_GRAPH` (which wires specific SQLAlchemy models
into EntitySpec instances) lives in the infrastructure adapter layer at:
    worker/adapters/replication_registry.py

Adding a new entity with FK constraints:
    1. Create its EntitySpec in replication_registry.py.
    2. Add it to REPLICATION_GRAPH there.
    The topological_layers algorithm and the generic replication driver will
    handle the rest automatically — no other changes required.
"""

from dataclasses import dataclass, field
from typing import Any

# ModelClass is Any because the actual model types are infrastructure concerns
# (SQLAlchemy DeclarativeBase subclasses) that must not be imported here.
# At all call sites in the adapter layer, they are always type[DeclarativeBase].
ModelClass = Any


@dataclass(frozen=True)
class EntityDependency:
    """
    Describes a single nullable FK field on an entity.

    Attributes:
        fk_attr:        The attribute name on the global SQLAlchemy model that
                        holds the foreign key value (e.g. "as2_partner_id").
        global_model:   The SQLAlchemy model class to query from the global DB.
        tenant_model:   The SQLAlchemy model class to upsert into the shard DB.
        include_shared: If True, the FK target may be a shared platform entity
                        (owned by PLATFORM_TENANT_ID). The upsert preserves the
                        source entity's own tenant_id rather than the requesting
                        tenant's ID.
    """

    fk_attr: str
    global_model: ModelClass
    tenant_model: ModelClass
    include_shared: bool = False


@dataclass(frozen=True)
class EntitySpec:
    """
    Full replication specification for a single entity type.

    Attributes:
        global_model:   SQLAlchemy model class in the global (control-plane) DB.
        tenant_model:   SQLAlchemy model class in the tenant (data-plane) shard DB.
        include_shared: If True, the query scope includes rows owned by
                        PLATFORM_TENANT_ID (shared platform configuration).
        dependencies:   Ordered list of FK dependencies that must be pre-replicated
                        before this entity can be safely upserted. Evaluated
                        left-to-right; null FK values are skipped automatically.
    """

    global_model: ModelClass
    tenant_model: ModelClass
    include_shared: bool = False
    dependencies: list[EntityDependency] = field(default_factory=list)


def topological_layers(graph: dict[str, EntitySpec]) -> list[list[str]]:
    """
    Compute the topological replication order of entities via Kahn's algorithm.

    Returns a list of layers. Each layer is a list of entity keys that have
    all their FK dependencies satisfied by earlier layers, and can therefore
    be safely replicated (or deleted in reverse) as a group.

    Raises:
        ValueError: If a dependency cycle is detected in the graph.

    Example:
        Given:  as2_partnership → as2_partner
                outbound_route  → as2_partner
        Returns: [["as2_partner", ...], ["as2_partnership", "outbound_route", ...]]
    """
    # Build a reverse lookup: global_model class → entity key
    model_to_key: dict[Any, str] = {spec.global_model: key for key, spec in graph.items()}

    # For each entity, compute the set of entity keys it depends on
    deps_by_key: dict[str, set[str]] = {}
    for key, spec in graph.items():
        dep_keys: set[str] = set()
        for dep in spec.dependencies:
            dep_key = model_to_key.get(dep.global_model)
            if dep_key is not None and dep_key != key:
                dep_keys.add(dep_key)
        deps_by_key[key] = dep_keys

    # Kahn's algorithm
    layers: list[list[str]] = []
    remaining: set[str] = set(graph.keys())
    resolved: set[str] = set()

    while remaining:
        # Entities whose all dependencies are already resolved are ready for this layer
        ready: set[str] = {k for k in remaining if deps_by_key[k].issubset(resolved)}

        if not ready:
            raise ValueError(
                f"Dependency cycle detected in REPLICATION_GRAPH. "
                f"Unresolvable entities: {sorted(remaining)}. "
                f"Check for circular FK references in replication_registry.py."
            )

        # Sort within each layer for deterministic ordering in tests and logs
        layers.append(sorted(ready))
        resolved |= ready
        remaining -= ready

    return layers
