"""Outbound/application ports for the sub-millisecond Authorization Policy Decision Point (PDP)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeVar

from identity.domain.dtos import AuthzDecision, AuthzRequest

_SessionT = TypeVar("_SessionT", contravariant=True)


class AuthorizationEnginePort(Protocol):
    """Evaluates an authorization request and returns a first-class immutable AuthzDecision."""

    async def evaluate(self, request: AuthzRequest) -> AuthzDecision: ...

    async def has_active_tenant_access(
        self,
        *,
        user_id: str,
        target_tenant_id: str,
        now: datetime | None = None,
    ) -> bool: ...


class AuthzRuntimePort(Protocol[_SessionT]):
    """Domain-agnostic host runtime contract for assembling request-scoped PDP engines."""

    def build_engine(self, session: _SessionT) -> AuthorizationEnginePort: ...

    async def has_hierarchical_tenant_access(
        self,
        *,
        session: _SessionT,
        user_id: str,
        target_tenant_id: str,
    ) -> bool: ...


__all__ = ["AuthorizationEnginePort", "AuthzRuntimePort"]
