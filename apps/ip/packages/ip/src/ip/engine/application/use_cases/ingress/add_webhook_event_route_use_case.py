"""CQRS Use case for attaching a multiplexed event route to a WebhookEndpoint."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.utils import generate_id

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.webhook.enums import PayloadSemantic
from ip.engine.domain.webhook.exceptions import WebhookEndpointNotFoundError
from ip.engine.domain.webhook.route import WebhookEventRoute
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AddWebhookEventRouteCommand:
    """Command to attach a multiplexed event route to an endpoint."""

    tenant_id: str
    endpoint_id: str
    event_pattern: str
    payload_semantic: PayloadSemantic
    target_pipeline_or_workflow_id: str
    description: str = ""
    priority: int = 100


@dataclass(frozen=True)
class AddWebhookEventRouteResult:
    """Result containing the ID of the created route."""

    route_id: str
    endpoint_id: str
    event_pattern: str
    payload_semantic: str
    target_pipeline_or_workflow_id: str
    priority: int


class AddWebhookEventRouteUseCase:
    """Attaches a multiplexed routing rule (DATA vs COMMAND) to an active WebhookEndpoint."""

    def __init__(self, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: AddWebhookEventRouteCommand
    ) -> Result[AddWebhookEventRouteResult, IpError]:
        log = logger.bind(
            tenant_id=command.tenant_id,
            endpoint_id=command.endpoint_id,
            event_pattern=command.event_pattern,
            semantic=command.payload_semantic.value,
        )
        log.info("add_webhook_event_route.started")

        async with self._uow:
            endpoint = await self._uow.webhook_endpoints.get_by_id(command.endpoint_id)
            if endpoint is None or endpoint.tenant_id != command.tenant_id:
                log.error("add_webhook_event_route.endpoint_not_found")
                return Result.fail(
                    WebhookEndpointNotFoundError.for_slug(command.tenant_id, command.endpoint_id)
                )

            route_id = generate_id(IpIdPrefix.WEBHOOK_EVENT_ROUTE.value)
            route = WebhookEventRoute(
                id=route_id,
                endpoint_id=command.endpoint_id,
                event_pattern=command.event_pattern.strip(),
                payload_semantic=command.payload_semantic,
                target_pipeline_or_workflow_id=command.target_pipeline_or_workflow_id.strip(),
                description=command.description.strip(),
                priority=command.priority,
                is_active=True,
            )

            endpoint.add_event_route(route)
            await self._uow.webhook_endpoints.save(endpoint)
            await self._uow.commit()

        log.info("add_webhook_event_route.completed", route_id=route_id)
        return Result.ok(
            AddWebhookEventRouteResult(
                route_id=route_id,
                endpoint_id=command.endpoint_id,
                event_pattern=command.event_pattern,
                payload_semantic=command.payload_semantic.value,
                target_pipeline_or_workflow_id=command.target_pipeline_or_workflow_id,
                priority=command.priority,
            )
        )
