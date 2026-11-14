"""CQRS Use case for rotating the secret of a WebhookEndpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ip.engine.domain.exceptions import IpError
from ip.engine.domain.webhook.exceptions import WebhookEndpointNotFoundError
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RotateWebhookSecretCommand:
    """Command to rotate an endpoint's secret."""

    tenant_id: str
    endpoint_id: str
    new_secret: str | None = None


@dataclass(frozen=True)
class RotateWebhookSecretResult:
    """Result containing the newly active primary secret token."""

    endpoint_id: str
    tenant_id: str
    new_secret_token: str
    secret_rotated_at: str


class RotateWebhookSecretUseCase:
    """Rotates secret, transitioning existing secret to secondary fallback to ensure zero downtime."""

    def __init__(self, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: RotateWebhookSecretCommand
    ) -> Result[RotateWebhookSecretResult, IpError]:
        log = logger.bind(tenant_id=command.tenant_id, endpoint_id=command.endpoint_id)
        log.info("rotate_webhook_secret.started")

        new_secret = command.new_secret or f"whsec_{os.urandom(16).hex()}"

        async with self._uow:
            endpoint = await self._uow.webhook_endpoints.get_by_id(command.endpoint_id)
            if endpoint is None or endpoint.tenant_id != command.tenant_id:
                log.error("rotate_webhook_secret.endpoint_not_found")
                return Result.fail(
                    WebhookEndpointNotFoundError.for_slug(command.tenant_id, command.endpoint_id)
                )

            endpoint.rotate_secret(new_secret)
            rotated_at = endpoint.secret_rotated_at or ""
            await self._uow.webhook_endpoints.save(endpoint)
            await self._uow.commit()

        log.info("rotate_webhook_secret.completed")
        return Result.ok(
            RotateWebhookSecretResult(
                endpoint_id=command.endpoint_id,
                tenant_id=command.tenant_id,
                new_secret_token=new_secret,
                secret_rotated_at=rotated_at,
            )
        )
