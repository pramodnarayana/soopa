"""Outbound port for resolving outbound connector authentication strategies."""

from __future__ import annotations

from typing import Protocol, TypeVar

from seedwork.domain.types import JsonDict

from ip.engine.domain.connection.enums import AuthType

TAuthenticator_co = TypeVar("TAuthenticator_co", covariant=True)


class AuthStrategyResolverPort(Protocol[TAuthenticator_co]):
    """Abstract port mapping connection auth configuration to a protocol-specific authenticator."""

    def resolve(
        self,
        auth_type: AuthType | str,
        credentials: JsonDict | bytes | str | None = None,
        *,
        allow_private_ips: bool = False,
    ) -> TAuthenticator_co: ...


__all__ = ["AuthStrategyResolverPort", "TAuthenticator_co"]
