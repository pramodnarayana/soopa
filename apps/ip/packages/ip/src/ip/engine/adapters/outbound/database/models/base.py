"""Base declarative models for Integration Platform Control Plane and Data Plane entities."""

from sqlalchemy.orm import DeclarativeBase, registry

IpGlobalRegistry = registry()
IpTenantRegistry = registry()

# Alias for Control Plane registry
IpRegistry = IpGlobalRegistry


class IpGlobalBase(DeclarativeBase):
    """Declarative base class for Control Plane models in the 'ip' schema of global_db."""

    registry = IpGlobalRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "ip"}


class IpTenantBase(DeclarativeBase):
    """Declarative base class for Data Plane & Canonical Domain models in tenant shards (public schema)."""

    registry = IpTenantRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {}


# Alias for Control Plane base
IpBase = IpGlobalBase

__all__ = [
    "IpBase",
    "IpGlobalBase",
    "IpGlobalRegistry",
    "IpRegistry",
    "IpTenantBase",
    "IpTenantRegistry",
]
