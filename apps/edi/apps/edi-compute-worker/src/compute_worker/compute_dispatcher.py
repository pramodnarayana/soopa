from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase

logger = structlog.get_logger(__name__)


class EdiComputeDispatcher:
    """
    Dispatcher that routes messages to the pure Python Use Case.
    """

    def __init__(
        self,
        use_case_factory: Callable[[str], Awaitable[ComputeTransformUseCase]],
    ):
        self.use_case_factory = use_case_factory

    async def dispatch_raw(self, body_json: dict[str, Any]) -> None:
        """Parses the SQS payload and invokes the pure Domain logic."""
        try:
            payload = body_json.get("payload", {})
            if not payload:
                # Fallback if the body is already the payload
                payload = body_json

            # Extract and validate required fields
            trace_id = payload.get("trace_id")
            standard = payload.get("standard", "X12")
            transaction_type = payload.get("transaction_type", "UNKNOWN")
            tenant_id = payload.get("tenant_id")

            if not trace_id or not isinstance(trace_id, str) or not trace_id.strip():
                raise ValueError("Required field 'trace_id' is missing or empty")

            if not tenant_id:
                raise ValueError("Required field 'tenant_id' is missing")

            trace_id = str(trace_id).strip()

            logger.info("sqs_message_received", trace_id=trace_id)

            # Execute Hexagonal Use Case dynamically instantiated for the correct Tenant
            use_case = await self.use_case_factory(tenant_id)

            await use_case.execute(
                trace_id=trace_id, standard=standard, transaction_type=transaction_type
            )

            logger.info("edi_transformed_successfully", trace_id=trace_id)

        except ValueError as e:
            logger.warning("edi_message_validation_failed", error=str(e))
            # SqsConsumerManager doesn't natively expose receipt handles or queues to handlers,
            # but raising an exception would return it to the queue.
            # If we swallow the ValueError (which means it's permanently invalid),
            # the manager will naturally delete it as if successful!
            # So just return here and the message will be deleted.
            return
        except Exception:
            logger.exception("edi_message_processing_failed")
            # Re-raise to prevent message deletion
            raise
