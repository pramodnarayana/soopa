from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from edi.application.use_cases.pipeline.compute_outbound_transform_use_case import (
    ComputeOutboundTransformCommand,
    ComputeOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.compute_transform_use_case import (
    ComputeTransformCommand,
    ComputeTransformUseCase,
)
from edi.domain.enums import EdiDirection, EdiStandard
from edi.domain.exceptions import InvalidMessageError
from pubsub.aws.debezium_parser import DebeziumPayloadParser

logger = structlog.get_logger(__name__)


class EdiComputeDispatcher:
    """
    Dispatcher that routes messages to the pure Python Use Case.
    """

    def __init__(
        self,
        use_case_factory: Callable[[str], Awaitable[ComputeTransformUseCase]],
        outbound_use_case_factory: Callable[[str], Awaitable[ComputeOutboundTransformUseCase]],
    ):
        self.use_case_factory = use_case_factory
        self.outbound_use_case_factory = outbound_use_case_factory

    def _parse_inbound_command(self, base_kwargs: dict[str, Any]) -> ComputeTransformCommand:
        return ComputeTransformCommand(**base_kwargs)

    def _parse_outbound_command(
        self, payload: dict[str, Any], base_kwargs: dict[str, Any]
    ) -> ComputeOutboundTransformCommand:
        raw_transaction_type = payload.get("transaction_type")
        if not raw_transaction_type or not str(raw_transaction_type).strip():
            raise InvalidMessageError(
                f"Missing or empty transaction_type in outbound compute event "
                f"for trace_id={payload.get('trace_id', 'unknown')}"
            )
        route_config = payload.get("route_config")
        if not isinstance(route_config, dict) or "connection_type" not in route_config:
            raise InvalidMessageError(
                f"Missing or invalid route_config (requires 'connection_type') in outbound compute event "
                f"for trace_id={payload.get('trace_id', 'unknown')}"
            )

        return ComputeOutboundTransformCommand(
            **base_kwargs,
            transaction_type=str(raw_transaction_type).strip(),
            route_config=route_config,
        )

    def _parse_command(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> ComputeTransformCommand | ComputeOutboundTransformCommand:
        direction_val = payload.get("direction")
        direction = str(direction_val if direction_val else EdiDirection.INBOUND.value)

        trace_id = payload.get("trace_id")
        tenant_id = payload.get("tenant_id")
        if not trace_id or not tenant_id:
            raise InvalidMessageError("Missing or empty trace_id or tenant_id in payload")

        base_kwargs = {
            "trace_id": str(trace_id),
            "tenant_id": str(tenant_id),
            "idempotency_key": idempotency_key,
            "standard": str(payload.get("standard", EdiStandard.X12.name)),
        }

        if direction == EdiDirection.INBOUND.value:
            return self._parse_inbound_command(base_kwargs)
        elif direction == EdiDirection.OUTBOUND.value:
            return self._parse_outbound_command(payload, base_kwargs)
        else:
            raise InvalidMessageError(f"Invalid direction: {direction}")

    async def dispatch_raw(self, body_json: dict[str, Any]) -> None:
        """Parses the SQS payload and invokes the pure Domain logic."""
        try:
            payload = DebeziumPayloadParser.extract_payload(body_json)
            if not payload:
                raise InvalidMessageError("Message payload must be a valid JSON dictionary")

            # idempotency_key is a top-level outbox column surfaced by Debezium,
            # NOT inside the payload JSONB blob.
            idempotency_key = body_json.get("idempotency_key")
            if not idempotency_key or not str(idempotency_key).strip():
                raise InvalidMessageError("Missing or empty 'idempotency_key' in message body")

            try:
                command = self._parse_command(payload, str(idempotency_key))
            except ValueError as e:
                raise InvalidMessageError(str(e))

        except InvalidMessageError as e:
            logger.warning("edi_message_validation_failed", error=str(e))
            # SqsConsumerManager doesn't natively expose receipt handles or queues to handlers,
            # but raising an exception would return it to the queue.
            # If we swallow the InvalidMessageError (which means it's permanently invalid),
            # the manager will naturally delete it as if successful!
            # So just return here and the message will be deleted.
            return

        try:
            logger.info("sqs_message_received", trace_id=command.trace_id)

            # Execute Hexagonal Use Case dynamically instantiated for the correct Tenant
            if isinstance(command, ComputeTransformCommand):
                inbound_use_case = await self.use_case_factory(command.tenant_id)
                await inbound_use_case.execute(command)
            else:
                outbound_use_case = await self.outbound_use_case_factory(command.tenant_id)
                await outbound_use_case.execute(command)

            logger.info("edi_transformed_successfully", trace_id=command.trace_id)

        except Exception:
            logger.exception("edi_message_processing_failed")
            # Re-raise to prevent message deletion
            raise
