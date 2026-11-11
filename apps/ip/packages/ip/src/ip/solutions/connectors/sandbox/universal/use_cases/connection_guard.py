"""Connection ownership and app_id verification guards for Simulator Entity use cases."""

from __future__ import annotations

from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    InvalidConnectionConfigError,
    IpError,
    Result,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.solutions.connectors.sandbox.universal.spec import (
    MAX_SIMULATOR_CURSOR_STEP_SECONDS,
    MAX_SIMULATOR_RECORDS_PER_PULL,
    MIN_SIMULATOR_CURSOR_STEP_SECONDS,
    MIN_SIMULATOR_RECORDS_PER_PULL,
    UNIVERSAL_SIMULATOR_APP_ID,
)


def validate_simulator_app_id(
    *,
    connection_id: str,
    app_id: str,
) -> InvalidConnectionConfigError | None:
    """Validates that `app_id` matches `UNIVERSAL_SIMULATOR_APP_ID`."""
    if app_id != UNIVERSAL_SIMULATOR_APP_ID:
        return InvalidConnectionConfigError(
            field_name="connection_id",
            message=(
                f"Connection '{connection_id}' (app_id='{app_id}') is not a "
                f"Universal Schema Simulator connection."
            ),
            details={"connection_id": connection_id, "app_id": app_id},
        )
    return None


def validate_simulator_entity_bounds(
    *,
    records_per_pull: int,
    cursor_step_seconds: int,
) -> InvalidConnectionConfigError | None:
    """Validates numeric range bounds for Simulator entity synthesis parameters."""
    if (
        records_per_pull < MIN_SIMULATOR_RECORDS_PER_PULL
        or records_per_pull > MAX_SIMULATOR_RECORDS_PER_PULL
    ):
        return InvalidConnectionConfigError(
            field_name="records_per_pull",
            message=(
                f"records_per_pull must be between {MIN_SIMULATOR_RECORDS_PER_PULL} "
                f"and {MAX_SIMULATOR_RECORDS_PER_PULL}."
            ),
            details={"field": "records_per_pull"},
        )
    if (
        cursor_step_seconds < MIN_SIMULATOR_CURSOR_STEP_SECONDS
        or cursor_step_seconds > MAX_SIMULATOR_CURSOR_STEP_SECONDS
    ):
        return InvalidConnectionConfigError(
            field_name="cursor_step_seconds",
            message=(
                f"cursor_step_seconds must be between {MIN_SIMULATOR_CURSOR_STEP_SECONDS} "
                f"and {MAX_SIMULATOR_CURSOR_STEP_SECONDS}."
            ),
            details={"field": "cursor_step_seconds"},
        )
    return None


def _validate_loaded_connection(
    connection: Connection | None,
    *,
    tenant_id: str,
    connection_id: str,
) -> Result[Connection, IpError]:
    if connection is None or connection.tenant_id != tenant_id:
        return Result.fail(ConnectionNotFoundError.for_id(connection_id))
    app_err = validate_simulator_app_id(
        connection_id=connection_id,
        app_id=connection.app_id,
    )
    if app_err is not None:
        return Result.fail(app_err)
    return Result.ok(connection)


async def verify_simulator_connection(
    connections: ConnectionRepositoryPort,
    *,
    tenant_id: str,
    connection_id: str,
) -> Result[Connection, IpError]:
    """Verifies that `connection_id` exists, belongs to `tenant_id`, and targets `universal_simulator`."""
    connection = await connections.get_by_id(connection_id)
    return _validate_loaded_connection(
        connection,
        tenant_id=tenant_id,
        connection_id=connection_id,
    )


async def lock_simulator_connection(
    connections: ConnectionRepositoryPort,
    *,
    tenant_id: str,
    connection_id: str,
) -> Result[Connection, IpError]:
    """Row-locks (`SELECT ... FOR UPDATE`) and verifies `connection_id` ownership and simulator type."""
    connection = await connections.get_by_id_for_update(connection_id)
    return _validate_loaded_connection(
        connection,
        tenant_id=tenant_id,
        connection_id=connection_id,
    )


__all__ = [
    "lock_simulator_connection",
    "validate_simulator_app_id",
    "validate_simulator_entity_bounds",
    "verify_simulator_connection",
]
