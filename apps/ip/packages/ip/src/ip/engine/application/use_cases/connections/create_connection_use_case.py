"""Use case to create and persist a new Connection aggregate."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id

from ip.engine.application.responses import ConnectionDTO, ConnectionOperationResultDTO
from ip.engine.domain.connection.connection import Connection, compute_connection_fingerprint
from ip.engine.domain.connection.enums import (
    AuthType,
    ConnectionStatus,
    EngineConnectorId,
    WebhookModality,
)
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    InvalidConnectionConfigError,
)
from ip.engine.domain.webhook.endpoint import WebhookEndpoint
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy
from ip.engine.domain.webhook.route import WebhookEventRoute
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateConnectionCommand:
    """Command payload to initialize a new connection."""

    tenant_id: str
    app_id: str
    name: str
    auth_type: str
    public_config: JsonDict
    raw_credentials: JsonDict
    endpoint_for_fingerprint: str | None = None


def _resolve_endpoint(command: CreateConnectionCommand) -> str:
    if command.endpoint_for_fingerprint:
        return command.endpoint_for_fingerprint
    for key in ("endpoint_slug", "endpoint_url", "base_url", "host"):
        val = command.public_config.get(key)
        if val:
            return str(val)
    return command.name


def _resolve_webhook_route_target(
    command: CreateConnectionCommand, clean_slug: str
) -> tuple[PayloadSemantic, str]:
    raw_modality = (
        str(
            command.public_config.get("webhook_modality")
            or command.public_config.get("payload_semantic")
            or ""
        )
        .strip()
        .upper()
    )

    if (
        raw_modality == WebhookModality.COMMAND.value
        or raw_modality == PayloadSemantic.COMMAND.value
    ):
        return PayloadSemantic.COMMAND, f"{clean_slug}_command"
    if raw_modality == WebhookModality.DATA.value or raw_modality == PayloadSemantic.DATA.value:
        return PayloadSemantic.DATA, f"{clean_slug}_pipeline"

    is_command = any(k in clean_slug for k in ("extract", "command", "mdm", "request"))
    semantic = PayloadSemantic.COMMAND if is_command else PayloadSemantic.DATA
    target_id = f"{clean_slug}_command" if is_command else f"{clean_slug}_pipeline"
    return semantic, target_id


class CreateConnectionUseCase:
    """Creates a new external application connection with encrypted credentials inside a Control Plane UoW."""

    def __init__(
        self,
        uow: IpControlPlaneUnitOfWorkPort,
        cipher: CipherPort,
    ) -> None:
        self._uow = uow
        self._cipher = cipher

    async def _create_bound_webhook_endpoint(
        self, command: CreateConnectionCommand, connection_id: str
    ) -> None:
        raw_slug = str(command.public_config.get("endpoint_slug") or command.name).strip().lower()
        clean_slug = re.sub(r"[^a-z0-9_-]", "-", raw_slug).strip("-") or "default-webhook"
        existing_ep = await self._uow.webhook_endpoints.get_by_slug(command.tenant_id, clean_slug)
        if existing_ep is not None:
            return

        raw_strategy = str(
            command.public_config.get("verification_strategy")
            or VerificationStrategy.PUBLIC_UNAUTHENTICATED.value
        ).upper()
        try:
            strat = VerificationStrategy(raw_strategy)
        except ValueError:
            strat = VerificationStrategy.PUBLIC_UNAUTHENTICATED

        secret_val = str(
            command.raw_credentials.get("secret_token")
            or command.public_config.get("secret_token")
            or ""
        ).strip()
        if not secret_val and strat != VerificationStrategy.PUBLIC_UNAUTHENTICATED:
            secret_val = f"whsec_{os.urandom(16).hex()}"

        ep = WebhookEndpoint.create(
            tenant_id=command.tenant_id,
            endpoint_slug=clean_slug,
            name=command.name,
            description=str(command.public_config.get("description", "")),
            verification_strategy=strat,
            primary_secret_hash=secret_val,
            bound_connection_id=connection_id,
        )

        semantic, target_id = _resolve_webhook_route_target(command, clean_slug)

        wildcard_route = WebhookEventRoute(
            id=generate_id(IpIdPrefix.WEBHOOK_EVENT_ROUTE.value),
            endpoint_id=ep.id,
            event_pattern="*",
            payload_semantic=semantic,
            target_pipeline_or_workflow_id=target_id,
            description=f"Default ingress route for {command.name}",
            priority=10000,
            is_active=True,
        )
        ep.add_event_route(wildcard_route)
        await self._uow.webhook_endpoints.save(ep)

    async def execute(self, command: CreateConnectionCommand) -> ConnectionOperationResultDTO:
        async with self._uow:
            try:
                auth_type = AuthType(command.auth_type)
            except ValueError:
                error = InvalidConnectionConfigError(
                    field_name="auth_type",
                    message=f"Unsupported authentication type '{command.auth_type}'.",
                    details={"auth_type": command.auth_type},
                )
                logger.error(
                    "connection_create_invalid_auth_type",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    auth_type=command.auth_type,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(error)

            endpoint = _resolve_endpoint(command)
            fingerprint = compute_connection_fingerprint(
                command.tenant_id, command.app_id, endpoint
            )

            existing = await self._uow.connections.get_by_fingerprint(
                command.tenant_id, fingerprint
            )
            if existing and existing.status != ConnectionStatus.DEACTIVATED:
                dup_error = DuplicateConnectionFingerprintError.create(
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    fingerprint=fingerprint,
                )
                logger.error(
                    "connection_duplicate_fingerprint_rejected",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    fingerprint=fingerprint,
                    error_code=dup_error.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(dup_error)

            encrypted_creds = (
                self._cipher.encrypt(command.raw_credentials) if command.raw_credentials else None
            )

            create_result = Connection.try_create(
                tenant_id=command.tenant_id,
                app_id=command.app_id,
                name=command.name,
                auth_type=auth_type,
                public_config=command.public_config,
                encrypted_credentials=encrypted_creds,
                endpoint_for_fingerprint=endpoint,
            )
            if create_result.error is not None or create_result.value is None:
                err = create_result.error or InvalidConnectionConfigError(
                    message="Invalid connection configuration."
                )
                logger.error(
                    "connection_create_validation_failed",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    error_code=err.code.value,
                    error_message=err.message,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(err)

            connection = create_result.value
            save_result = await self._uow.connections.save(connection)
            if save_result.error is not None:
                logger.error(
                    "connection_save_conflict",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    fingerprint=fingerprint,
                    error_code=save_result.error.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(save_result.error)

            if connection.app_id == EngineConnectorId.WEBHOOK.value:
                await self._create_bound_webhook_endpoint(command, connection.id)

            await self._uow.commit()

            logger.info(
                "connection_created",
                connection_id=connection.id,
                tenant_id=command.tenant_id,
                app_id=command.app_id,
                connection_fingerprint=fingerprint,
                auth_type=command.auth_type,
            )

            return ConnectionOperationResultDTO.ok(ConnectionDTO.from_domain(connection))
