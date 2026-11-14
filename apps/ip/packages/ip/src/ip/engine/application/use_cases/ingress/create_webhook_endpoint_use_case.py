"""CQRS Use case for provisioning a new WebhookEndpoint aggregate root."""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.utils import generate_id

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.webhook.endpoint import WebhookEndpoint
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy
from ip.engine.domain.webhook.exceptions import (
    DuplicateWebhookEndpointSlugError,
)
from ip.engine.domain.webhook.route import WebhookEventRoute
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateWebhookEndpointCommand:
    """Command to provision a new passive inbound webhook endpoint."""

    tenant_id: str
    endpoint_slug: str
    name: str
    description: str = ""
    verification_strategy: VerificationStrategy = VerificationStrategy.SHARED_HEADER_SECRET
    primary_secret: str | None = None
    bound_connection_id: str | None = None


@dataclass(frozen=True)
class CreateWebhookEndpointResult:
    """Structured response containing clean URL and the secret token (returned once)."""

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str
    name: str
    verification_strategy: str
    secret_token: str
    permanent_url_path: str
    bound_connection_id: str | None = None


class CreateWebhookEndpointUseCase:
    """Provisions a new WebhookEndpoint with clean slug and default wildcard route."""

    def __init__(self, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: CreateWebhookEndpointCommand
    ) -> Result[CreateWebhookEndpointResult, IpError]:
        clean_slug = command.endpoint_slug.strip().lower()
        log = logger.bind(
            tenant_id=command.tenant_id,
            endpoint_slug=clean_slug,
            name=command.name,
        )
        log.info("create_webhook_endpoint.started")

        async with self._uow:
            existing = await self._uow.webhook_endpoints.get_by_slug(command.tenant_id, clean_slug)
            if existing is not None:
                log.error("create_webhook_endpoint.slug_already_exists")
                return Result.fail(DuplicateWebhookEndpointSlugError())

            secret = command.primary_secret or f"whsec_{os.urandom(16).hex()}"
            endpoint_id = generate_id(IpIdPrefix.WEBHOOK_ENDPOINT.value)

            endpoint = WebhookEndpoint.create(
                endpoint_id=endpoint_id,
                tenant_id=command.tenant_id,
                endpoint_slug=clean_slug,
                name=command.name,
                description=command.description,
                verification_strategy=command.verification_strategy,
                primary_secret_hash=secret,
                bound_connection_id=command.bound_connection_id,
            )

            # Provision default wildcard route
            wildcard_route = WebhookEventRoute(
                id=generate_id(IpIdPrefix.WEBHOOK_EVENT_ROUTE.value),
                endpoint_id=endpoint_id,
                event_pattern="*",
                payload_semantic=PayloadSemantic.DATA,
                target_pipeline_or_workflow_id="default_data_pipeline",
                description="Default wildcard route for unclassified vendor data drops",
                priority=999,
                is_active=True,
            )
            endpoint.add_event_route(wildcard_route)

            await self._uow.webhook_endpoints.save(endpoint)
            await self._uow.commit()

        permanent_url_path = f"/api/v1/ingress/{command.tenant_id}/{clean_slug}"
        log.info(
            "create_webhook_endpoint.completed",
            endpoint_id=endpoint_id,
            permanent_url=permanent_url_path,
        )

        return Result.ok(
            CreateWebhookEndpointResult(
                endpoint_id=endpoint_id,
                tenant_id=command.tenant_id,
                endpoint_slug=clean_slug,
                name=command.name,
                verification_strategy=command.verification_strategy.value,
                secret_token=secret,
                permanent_url_path=permanent_url_path,
                bound_connection_id=command.bound_connection_id,
            )
        )
