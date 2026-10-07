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
from edi.domain.models.headers import EdiEnvelopeHeaders
from pubsub.exceptions import ConsumerTerminalError

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
        try:
            raw_transaction_type = payload["transaction_type"]
            isa_sender_id = payload["isa_sender_id"]
            isa_receiver_id = payload["isa_receiver_id"]
            gs_sender_id = payload["gs_sender_id"]
            gs_receiver_id = payload["gs_receiver_id"]
            isa_usage_indicator = payload.get("isa_usage_indicator")
        except KeyError as e:
            raise InvalidMessageError(f"Missing required field in outbound payload: {e}")

        if not raw_transaction_type or not str(raw_transaction_type).strip():
            raise InvalidMessageError("Missing or empty transaction_type in outbound compute event")

        if not isa_sender_id or not isa_receiver_id:
            raise InvalidMessageError(
                "Missing or empty isa_sender_id or isa_receiver_id in outbound compute event"
            )

        if not gs_sender_id or not gs_receiver_id:
            raise InvalidMessageError(
                "Missing or empty gs_sender_id or gs_receiver_id in outbound compute event"
            )

        if not isa_usage_indicator:
            raise InvalidMessageError(
                "Missing or empty isa_usage_indicator in outbound compute event"
            )

        return ComputeOutboundTransformCommand(
            **base_kwargs,
            edi_headers=EdiEnvelopeHeaders(
                transaction_type=str(raw_transaction_type).strip(),
                isa_sender_id=str(isa_sender_id).strip(),
                isa_receiver_id=str(isa_receiver_id).strip(),
                gs_sender_id=str(gs_sender_id).strip(),
                gs_receiver_id=str(gs_receiver_id).strip(),
                isa_usage_indicator=str(isa_usage_indicator).strip(),
            ),
        )

    def _parse_command(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> ComputeTransformCommand | ComputeOutboundTransformCommand:
        direction_val = payload.get("direction")
        standard_val = payload.get("standard")
        try:
            trace_id = payload["trace_id"]
            tenant_id = payload["tenant_id"]
        except KeyError as e:
            raise InvalidMessageError(f"Missing required field in payload: {e}")

        direction = str(direction_val if direction_val else EdiDirection.INBOUND.value)

        if not trace_id or not tenant_id:
            raise InvalidMessageError("Missing or empty trace_id or tenant_id in payload")

        base_kwargs = {
            "trace_id": str(trace_id),
            "tenant_id": str(tenant_id),
            "idempotency_key": idempotency_key,
            "standard": str(standard_val) if standard_val else EdiStandard.X12.value,
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
            payload = body_json.get("payload")
            if not payload:
                raise InvalidMessageError("Message payload must be a valid JSON dictionary")

            idempotency_key = body_json.get("idempotency_key")
            if not idempotency_key or not str(idempotency_key).strip():
                raise InvalidMessageError("Missing or empty 'idempotency_key' in message body")

            try:
                command = self._parse_command(payload, str(idempotency_key))
            except ValueError as e:
                raise InvalidMessageError(str(e))

        except InvalidMessageError as e:
            logger.exception("edi_message_validation_failed", error=str(e))
            raise ConsumerTerminalError(f"Permanently malformed EDI compute message: {e}") from e

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
