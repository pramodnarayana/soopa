"""Outbound ports for distributed OAuth2 token refresh locking and token exchange."""

from __future__ import annotations

import contextlib
from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import IpError, Result


@dataclass(frozen=True)
class RefreshedOAuth2TokensDTO:
    """Strongly-typed result of an OAuth2 token refresh exchange."""

    access_token: str
    refresh_token: str | None
    expires_at_epoch: float | None


class TokenRefreshLockPort(Protocol):
    """Port for coordinating concurrent OAuth2 token refreshes per connection_id."""

    @abstractmethod
    def acquire(self, connection_id: str) -> contextlib.AbstractAsyncContextManager[None]:
        """Acquires an exclusive lock scoped to `connection_id` for the duration of the context."""
        ...


class OAuth2TokenRefresherPort(Protocol):
    """Port for executing an OAuth2 token refresh request against an Identity Provider."""

    @abstractmethod
    async def refresh_tokens(
        self,
        *,
        public_config: JsonDict,
        credentials: JsonDict,
        grant_mode: str = "refresh_token",
    ) -> Result[RefreshedOAuth2TokensDTO, IpError]:
        """Exchanges a refresh_token or client_credentials for a fresh access_token."""
        ...


__all__ = [
    "OAuth2TokenRefresherPort",
    "RefreshedOAuth2TokensDTO",
    "TokenRefreshLockPort",
]
