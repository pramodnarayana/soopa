"""Outbound/application port for the sub-millisecond Authorization Policy Decision Point (PDP)."""

from __future__ import annotations

from typing import Protocol

from identity.domain.dtos import AuthzDecision, AuthzRequest


class AuthorizationEnginePort(Protocol):
    """Evaluates an authorization request and returns a first-class immutable AuthzDecision."""

    async def evaluate(self, request: AuthzRequest) -> AuthzDecision: ...


__all__ = ["AuthorizationEnginePort"]
