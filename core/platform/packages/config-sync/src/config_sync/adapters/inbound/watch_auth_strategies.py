"""Polymorphic Authentication Strategies for Control Plane Dynamic Watch HTTP/SSE routes."""

from __future__ import annotations

import hmac

import structlog
from seedwork.domain.exceptions import Result

from config_sync.domain.dtos import ConfigSyncError
from config_sync.domain.enums import ConfigSyncErrorCode
from config_sync.ports.config_watch_auth_port import ConfigWatchAuthStrategyPort

logger = structlog.get_logger(__name__)


class BearerTokenWatchAuthStrategy(ConfigWatchAuthStrategyPort):
    """Constant-time Bearer token verifier enforcing authenticated Data Plane watch connections."""

    def __init__(self, expected_token: str) -> None:
        cleaned = expected_token.strip()
        if not cleaned:
            raise ValueError("BearerTokenWatchAuthStrategy requires a non-empty token.")
        self._expected_token = cleaned

    def verify(self, authorization: str | None) -> Result[None, ConfigSyncError]:
        if not authorization or not authorization.startswith("Bearer "):
            logger.error("config_watch_unauthorized_missing_bearer")
            return Result.fail(
                ConfigSyncError(
                    code=ConfigSyncErrorCode.UNAUTHORIZED,
                    message="Missing or invalid Bearer token for internal config watch.",
                )
            )
        supplied = authorization[7:].strip()
        if not hmac.compare_digest(supplied, self._expected_token):
            logger.error("config_watch_unauthorized_invalid_token")
            return Result.fail(
                ConfigSyncError(
                    code=ConfigSyncErrorCode.UNAUTHORIZED,
                    message="Invalid Bearer token for internal config watch.",
                )
            )
        return Result.ok(None)


class FailClosedUnconfiguredAuthStrategy(ConfigWatchAuthStrategyPort):
    """Default fail-closed strategy rejecting requests when no internal sync token is configured."""

    def verify(self, authorization: str | None) -> Result[None, ConfigSyncError]:
        del authorization
        logger.error("config_watch_internal_token_not_configured")
        return Result.fail(
            ConfigSyncError(
                code=ConfigSyncErrorCode.UNCONFIGURED_AUTH,
                message="Internal config watch authentication token is not configured.",
            )
        )


class AllowUnauthenticatedDevWatchAuthStrategy(ConfigWatchAuthStrategyPort):
    """Explicit opt-in strategy for local development environments without a configured sync token."""

    def verify(self, authorization: str | None) -> Result[None, ConfigSyncError]:
        del authorization
        return Result.ok(None)


__all__ = [
    "AllowUnauthenticatedDevWatchAuthStrategy",
    "BearerTokenWatchAuthStrategy",
    "FailClosedUnconfiguredAuthStrategy",
]
