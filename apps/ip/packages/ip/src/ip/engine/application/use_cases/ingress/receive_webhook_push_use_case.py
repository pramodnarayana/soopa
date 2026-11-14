"""CQRS Use case for handling inbound perimeter webhook pushes with 3-tier discrimination."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id
from webhooks.receivers.guards.crypto_verifier import TimingSafeInboundVerifier
from webhooks.receivers.guards.discriminator import resolve_event_discriminator
from webhooks.receivers.ports.inbound_verifier_port import InboundVerifierPort

from ip.engine.domain.constants import DEFAULT_INLINE_THRESHOLD_BYTES, IpIdPrefix
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.replication.enums import IngestionMode
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.webhook.exceptions import (
    UnmappedEventRouteError,
    WebhookEndpointDeactivatedError,
    WebhookEndpointNotFoundError,
    WebhookVerificationFailedError,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReceiveWebhookPushCommand:
    """Command to ingest an external vendor push at the L1 perimeter edge."""

    tenant_id: str
    endpoint_slug: str
    raw_payload: bytes
    headers: Mapping[str, str]
    query_params: Mapping[str, str]
    correlation_id: str | None = None


@dataclass(frozen=True)
class ReceiveWebhookPushResult:
    """Sub-20ms acknowledgment DTO returned to the calling vendor."""

    trace_id: str
    record_id: str
    status: str
    semantic: str
    matched_event_pattern: str
    target_pipeline_or_workflow_id: str


class ReceiveWebhookPushUseCase:
    """L1 Ingress Perimeter Gateway orchestrating authentication, 3-tier event discrimination,

    root trace inception, and sub-20ms ACID journal persistence.
    """

    def __init__(
        self,
        *,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        verifier: InboundVerifierPort | None = None,
    ) -> None:
        self._cp_uow = control_plane_uow
        self._dp_uow_provider = data_plane_uow_provider
        self._verifier = verifier or TimingSafeInboundVerifier()

    async def execute(
        self, command: ReceiveWebhookPushCommand
    ) -> Result[ReceiveWebhookPushResult, IpError]:
        clean_slug = command.endpoint_slug.strip().lower()
        log = logger.bind(
            tenant_id=command.tenant_id,
            endpoint_slug=clean_slug,
            correlation_id=command.correlation_id,
        )
        log.info("receive_webhook_push.received")

        # 1. Resolve WebhookEndpoint from Control Plane
        async with self._cp_uow:
            endpoint = await self._cp_uow.webhook_endpoints.get_by_slug(
                command.tenant_id, clean_slug
            )
            if endpoint is None:
                log.error("receive_webhook_push.endpoint_not_found")
                return Result.fail(
                    WebhookEndpointNotFoundError.for_slug(command.tenant_id, clean_slug)
                )

            if not endpoint.is_active:
                log.error("receive_webhook_push.endpoint_deactivated")
                return Result.fail(
                    WebhookEndpointDeactivatedError.for_slug(command.tenant_id, clean_slug)
                )

            # Copy aggregate properties to avoid keeping session open during data plane work
            verification_strategy = endpoint.verification_strategy
            primary_secret = endpoint.primary_secret_hash
            secondary_secret = endpoint.secondary_secret_hash
            bound_connection_id = endpoint.bound_connection_id or ""

        # 2. Timing-safe cryptographic & token verification
        is_verified = self._verifier.verify(
            strategy=verification_strategy,
            headers=command.headers,
            query_params=command.query_params,
            raw_body=command.raw_payload,
            primary_secret=primary_secret,
            secondary_secret=secondary_secret,
        )
        if not is_verified:
            log.error("receive_webhook_push.verification_failed")
            return Result.fail(WebhookVerificationFailedError())

        # 3. Parse JSON body safely for Tier 2 discrimination
        parsed_body: JsonDict | None = None
        if command.raw_payload:
            try:
                decoded = json.loads(command.raw_payload)
                if isinstance(decoded, dict):
                    parsed_body = decoded
            except (json.JSONDecodeError, UnicodeDecodeError):
                parsed_body = None

        # 4. Resolve 3-Tier discriminator (Headers -> Body -> Query -> Wildcard)
        discriminator = resolve_event_discriminator(
            command.headers,
            parsed_body,
            command.query_params,
        )

        matched_route = endpoint.match_route(discriminator)
        if matched_route is None:
            log.error(
                "receive_webhook_push.unmapped_event_route",
                discriminator=discriminator,
            )
            return Result.fail(UnmappedEventRouteError.for_event(clean_slug, discriminator))

        # 5. Incept root trace ID & persist L1 Inbound Record in Data Plane
        trace_id = generate_id(IpIdPrefix.TRACE.value)
        is_inlined = len(command.raw_payload) <= DEFAULT_INLINE_THRESHOLD_BYTES

        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            shard_err = shard_res.unwrap_err()
            log.error(
                "receive_webhook_push.shard_resolution_failed",
                tenant_id=command.tenant_id,
                error_code=shard_err.code.value,
            )
            return Result.fail(shard_err)
        shard_id, shard_dsn = shard_res.unwrap()

        async with self._dp_uow_provider.get_data_plane_uow(
            tenant_id=command.tenant_id,
            shard_id=shard_id,
            shard_dsn=shard_dsn,
        ) as dp_uow:
            inbound_record = InboundRecord.create(
                tenant_id=command.tenant_id,
                connection_id=bound_connection_id,
                app_id=clean_slug,
                stream_name=matched_route.event_pattern,
                payload_bytes=command.raw_payload,
                is_inlined=is_inlined,
                trace_id=trace_id,
                correlation_id=command.correlation_id,
                ingestion_mode=IngestionMode.PUSH_FULL,
            )

            await dp_uow.inbound_records.save(inbound_record)
            await dp_uow.commit()

        log.info(
            "receive_webhook_push.accepted",
            trace_id=trace_id,
            record_id=inbound_record.id,
            semantic=matched_route.payload_semantic.value,
            target=matched_route.target_pipeline_or_workflow_id,
        )

        return Result.ok(
            ReceiveWebhookPushResult(
                trace_id=trace_id,
                record_id=inbound_record.id,
                status="ACCEPTED",
                semantic=matched_route.payload_semantic.value,
                matched_event_pattern=matched_route.event_pattern,
                target_pipeline_or_workflow_id=matched_route.target_pipeline_or_workflow_id,
            )
        )
