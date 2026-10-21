"""Base declarative model for Integration Platform database entities."""

from sqlalchemy.orm import DeclarativeBase, registry

IpRegistry = registry()


class IpBase(DeclarativeBase):
    """Declarative base class for Integration Platform models in the 'ip' schema."""

    registry = IpRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "ip"}


__all__ = ["IpBase", "IpRegistry"]
