"""Outbound Ports for Open-Closed Home Realm Discovery (HRD) resolvers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from identity.domain.dtos import HomeRealmDecisionDTO


@runtime_checkable
class HomeRealmResolverPort(Protocol):
    """Conditional Home Realm Discovery resolver returning a decision or ``None``."""

    @property
    def name(self) -> str:
        """Stable observability name identifying this resolver strategy."""
        ...

    def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO | None:
        """Returns a ``HomeRealmDecisionDTO`` if this strategy claims ``domain``, else ``None``."""
        ...


@runtime_checkable
class FallbackHomeRealmResolverPort(Protocol):
    """Unconditional terminal Home Realm Discovery resolver guaranteeing anti-enumeration."""

    @property
    def name(self) -> str:
        """Stable observability name identifying this fallback strategy."""
        ...

    def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO:
        """Always returns a ``HomeRealmDecisionDTO`` for unclaimed or unrecognized domains."""
        ...
