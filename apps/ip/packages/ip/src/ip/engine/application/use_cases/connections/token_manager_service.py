"""Centralized, cross-layer OAuth2 credential manager with double-checked locking and single-use token rotation.

Shared across:
- Layer 0 (Catalog Discovery & Health Checks)
- Layer 1 (Inbound Pull Sync `RunSyncUseCase` & Thin-Push `FetchRecordUseCase`)
- Layer 5 (Outbound Delivery `DeliverOutboundRecordUseCase`)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict

from ip.engine.domain.constants import DEFAULT_TOKEN_REFRESH_BUFFER_SECONDS
from ip.engine.domain.enums import (
    AuthType,
    ConnectionStatus,
    FailureDisposition,
    TokenRefreshPolicy,
)
from ip.engine.domain.exceptions import (
    ConnectionDeactivatedError,
    ConnectionNotFoundError,
    InvalidCredentialsError,
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    TokenRefreshLockPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GetValidCredentialsCommand:
    """Command requesting valid (and if necessary, refreshed) credentials for a Connection."""

    tenant_id: str
    connection_id: str
    refresh_policy: TokenRefreshPolicy = TokenRefreshPolicy.PROACTIVE_IF_EXPIRING
    stale_access_token: str | None = None


@dataclass(frozen=True)
class ResolvedConnectionCredentialsDTO:
    """Strongly-typed credentials and configuration resolved for a Connection."""

    connection_id: str
    app_id: str
    auth_type: AuthType
    public_config: JsonDict
    credentials: JsonDict
    connection: Connection | None = None
    was_refreshed: bool = False


class TokenManagerService:
    """Single source of truth for OAuth2 token freshness across all IP layers (L0, L1, L5)."""

    def __init__(
        self,
        *,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        cipher: CipherPort,
        lock_port: TokenRefreshLockPort | None = None,
        token_refresher: OAuth2TokenRefresherPort | None = None,
        refresh_buffer_seconds: int = DEFAULT_TOKEN_REFRESH_BUFFER_SECONDS,
    ) -> None:
        self._control_plane_uow = control_plane_uow
        self._cipher = cipher
        self._lock_port = lock_port
        self._token_refresher = token_refresher
        self._refresh_buffer_seconds = refresh_buffer_seconds

    @staticmethod
    def _is_oauth2(auth_type: AuthType) -> bool:
        return auth_type in (AuthType.OAUTH2, AuthType.OAUTH2_CLIENT_CREDENTIALS)

    def _resolve_expires_at_epoch(
        self,
        connection: Connection,
        credentials: JsonDict,
    ) -> float | None:
        raw_epoch = credentials.get("expires_at_epoch")
        if isinstance(raw_epoch, (int, float)):
            return float(raw_epoch)
        if isinstance(raw_epoch, str):
            try:
                return float(raw_epoch)
            except ValueError:
                pass
        if connection.token_expires_at:
            try:
                parsed = datetime.fromisoformat(connection.token_expires_at)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.timestamp()
            except ValueError:
                pass
        return None

    def _is_token_fresh(
        self,
        connection: Connection,
        credentials: JsonDict,
        *,
        now_epoch: float | None = None,
    ) -> bool:
        if not self._is_oauth2(connection.auth_type):
            return True
        access_token = str(credentials.get("access_token") or "").strip()
        if not access_token:
            return False
        expires_at = self._resolve_expires_at_epoch(connection, credentials)
        if expires_at is None:
            return True
        current_epoch = now_epoch if now_epoch is not None else datetime.now(UTC).timestamp()
        return current_epoch < (expires_at - self._refresh_buffer_seconds)

    async def _try_fast_path(
        self,
        command: GetValidCredentialsCommand,
    ) -> Result[ResolvedConnectionCredentialsDTO, IpError] | None:
        async with self._control_plane_uow:
            connection = await self._control_plane_uow.connections.get_by_id(command.connection_id)
            if connection is None or connection.tenant_id != command.tenant_id:
                logger.error(
                    "token_manager_connection_not_found",
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                )
                return Result.fail(ConnectionNotFoundError.for_id(command.connection_id))

            if connection.status is ConnectionStatus.DEACTIVATED:
                logger.error(
                    "token_manager_connection_deactivated",
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                )
                return Result.fail(ConnectionDeactivatedError.for_id(command.connection_id))

            fast_creds: JsonDict = (
                self._cipher.decrypt(connection.encrypted_credentials)
                if connection.encrypted_credentials
                else {}
            )
            if not self._is_oauth2(connection.auth_type) or (
                command.refresh_policy is TokenRefreshPolicy.PROACTIVE_IF_EXPIRING
                and self._is_token_fresh(connection, fast_creds)
            ):
                return Result.ok(
                    ResolvedConnectionCredentialsDTO(
                        connection_id=connection.id,
                        app_id=connection.app_id,
                        auth_type=connection.auth_type,
                        public_config=connection.resolved_public_config,
                        credentials=fast_creds,
                        connection=connection,
                        was_refreshed=False,
                    )
                )
        return None

    def _check_double_checked_cache_hit(
        self,
        command: GetValidCredentialsCommand,
        locked_conn: Connection,
        db_creds: JsonDict,
    ) -> ResolvedConnectionCredentialsDTO | None:
        db_access_token = str(db_creds.get("access_token") or "").strip()
        if (
            command.refresh_policy is TokenRefreshPolicy.FORCE_ROTATION
            and command.stale_access_token
            and db_access_token
            and db_access_token != command.stale_access_token
        ):
            logger.info(
                "token_manager_double_check_hit_rotated",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
            return ResolvedConnectionCredentialsDTO(
                connection_id=locked_conn.id,
                app_id=locked_conn.app_id,
                auth_type=locked_conn.auth_type,
                public_config=locked_conn.resolved_public_config,
                credentials=db_creds,
                connection=locked_conn,
                was_refreshed=False,
            )

        if (
            command.refresh_policy is TokenRefreshPolicy.PROACTIVE_IF_EXPIRING
            and self._is_token_fresh(locked_conn, db_creds)
        ):
            logger.info(
                "token_manager_double_check_hit_fresh",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
            return ResolvedConnectionCredentialsDTO(
                connection_id=locked_conn.id,
                app_id=locked_conn.app_id,
                auth_type=locked_conn.auth_type,
                public_config=locked_conn.resolved_public_config,
                credentials=db_creds,
                connection=locked_conn,
                was_refreshed=False,
            )
        return None

    async def _handle_refresh_error(
        self,
        command: GetValidCredentialsCommand,
        locked_conn: Connection,
        err: IpError,
    ) -> Result[ResolvedConnectionCredentialsDTO, IpError]:
        if err.disposition is FailureDisposition.RETRY:
            logger.warning(
                "token_manager_refresh_transient_failure",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                error_code=err.code.value,
                error_message=err.message,
            )
            return Result.fail(err)

        locked_conn.mark_error(
            error_code=IpErrorCode.UNAUTHORIZED.value,
            error_message=err.message,
        )
        await self._control_plane_uow.connections.save(locked_conn)
        await self._control_plane_uow.commit()
        logger.error(
            "token_manager_refresh_failed",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            error_code=err.code.value,
            error_message=err.message,
        )
        return Result.fail(err)

    async def get_valid_credentials(
        self,
        command: GetValidCredentialsCommand,
    ) -> Result[ResolvedConnectionCredentialsDTO, IpError]:
        """Returns valid connection credentials, refreshing OAuth2 tokens under lock when required."""
        fast_result = await self._try_fast_path(command)
        if fast_result is not None:
            return fast_result

        lock_cm = (
            self._lock_port.acquire(command.connection_id)
            if self._lock_port is not None
            else contextlib.nullcontext()
        )
        async with (
            lock_cm,
            self._control_plane_uow,
        ):
            locked_conn = await self._control_plane_uow.connections.get_by_id_for_update(
                command.connection_id
            )
            if locked_conn is None or locked_conn.tenant_id != command.tenant_id:
                return Result.fail(ConnectionNotFoundError.for_id(command.connection_id))

            if locked_conn.status is ConnectionStatus.DEACTIVATED:
                return Result.fail(ConnectionDeactivatedError.for_id(command.connection_id))

            db_creds: JsonDict = (
                self._cipher.decrypt(locked_conn.encrypted_credentials)
                if locked_conn.encrypted_credentials
                else {}
            )
            cache_hit = self._check_double_checked_cache_hit(command, locked_conn, db_creds)
            if cache_hit is not None:
                return Result.ok(cache_hit)

            if self._token_refresher is None:
                return Result.fail(
                    InvalidCredentialsError(
                        field_name="refresh_token",
                        message="OAuth2 token refresher is not configured.",
                    )
                )

            grant_mode = (
                "client_credentials"
                if locked_conn.auth_type is AuthType.OAUTH2_CLIENT_CREDENTIALS
                else "refresh_token"
            )
            refresh_res = await self._token_refresher.refresh_tokens(
                public_config=locked_conn.resolved_public_config,
                credentials=db_creds,
                grant_mode=grant_mode,
            )

            if refresh_res.is_err or refresh_res.value is None:
                err = refresh_res.error or InvalidCredentialsError(
                    field_name="refresh_token",
                    message="OAuth2 token refresh failed.",
                )
                return await self._handle_refresh_error(command, locked_conn, err)

            refreshed = refresh_res.value
            merged_creds: JsonDict = dict(db_creds)
            merged_creds["access_token"] = refreshed.access_token
            if refreshed.refresh_token:
                merged_creds["refresh_token"] = refreshed.refresh_token
            if refreshed.expires_at_epoch is not None:
                merged_creds["expires_at_epoch"] = refreshed.expires_at_epoch

            token_expires_iso = (
                datetime.fromtimestamp(refreshed.expires_at_epoch, tz=UTC).isoformat()
                if refreshed.expires_at_epoch is not None
                else locked_conn.token_expires_at
            )
            encrypted_bytes = self._cipher.encrypt(merged_creds)
            locked_conn.update_tokens(
                encrypted_credentials=encrypted_bytes,
                token_expires_at=token_expires_iso,
            )
            await self._control_plane_uow.connections.save(locked_conn)
            await self._control_plane_uow.commit()

            logger.info(
                "token_manager_token_refreshed",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                app_id=locked_conn.app_id,
                token_expires_at=token_expires_iso,
            )
            return Result.ok(
                ResolvedConnectionCredentialsDTO(
                    connection_id=locked_conn.id,
                    app_id=locked_conn.app_id,
                    auth_type=locked_conn.auth_type,
                    public_config=locked_conn.resolved_public_config,
                    credentials=merged_creds,
                    connection=locked_conn,
                    was_refreshed=True,
                )
            )


__all__ = [
    "GetValidCredentialsCommand",
    "ResolvedConnectionCredentialsDTO",
    "TokenManagerService",
]
