"""First-class Result[T, IpError] -> ConsumerAction disposition handler for IP Workers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

import structlog
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordResponse,
)
from ip.engine.domain.enums import FailureDisposition, OutboundDispatchStatus
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from pubsub.enums import ConsumerAction
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class IpWorkerResultDispositionHandler:
    """Translates single or chunked `Result[T, IpError]` outcomes into `ConsumerAction` verdicts.

    Zero exceptions are raised for known operational or domain errors:
    - Any `FailureDisposition.RETRY` -> `ConsumerAction.NACK` (retried by SQS visibility backoff).
    - Any `FailureDisposition.FAIL` (when no `RETRY` is present) -> `ConsumerAction.DLQ` (acknowledged / dead-lettered without infinite poison-pill loops).
    - `Result.is_ok` or `FailureDisposition.IGNORE` -> `ConsumerAction.ACK`.
    """

    @staticmethod
    def to_consumer_action(
        envelope: EventEnvelope,
        result: Result[T, IpError],
    ) -> ConsumerAction:
        return IpWorkerResultDispositionHandler.to_chunk_consumer_action(
            envelope,
            (result,),
        )

    @staticmethod
    def to_chunk_consumer_action(
        envelope: EventEnvelope,
        results: Sequence[Result[T, IpError]],
    ) -> ConsumerAction:
        retry_errors: list[IpError] = []
        fail_errors: list[IpError] = []
        ignore_errors: list[IpError] = []

        for res in results:
            if res.is_err and res.error is not None:
                err = res.error
                if err.disposition is FailureDisposition.RETRY:
                    retry_errors.append(err)
                elif err.disposition is FailureDisposition.IGNORE:
                    ignore_errors.append(err)
                else:
                    fail_errors.append(err)

        if retry_errors:
            first_retry = retry_errors[0]
            logger.warning(
                "ip_worker_chunk_retry_scheduled",
                event_id=envelope.id,
                event_type=envelope.event_type,
                tenant_id=envelope.tenant_id,
                trace_id=envelope.trace_id,
                lane=envelope.lane.value,
                retry_count=len(retry_errors),
                total_items=len(results),
                error_code=first_retry.code.value,
                reason=first_retry.message,
            )
            return ConsumerAction.NACK

        if fail_errors:
            first_fail = fail_errors[0]
            logger.error(
                "ip_worker_chunk_terminal_failure",
                event_id=envelope.id,
                event_type=envelope.event_type,
                tenant_id=envelope.tenant_id,
                trace_id=envelope.trace_id,
                lane=envelope.lane.value,
                fail_count=len(fail_errors),
                total_items=len(results),
                error_code=first_fail.code.value,
                reason=first_fail.message,
            )
            return ConsumerAction.DLQ

        if ignore_errors:
            logger.info(
                "ip_worker_chunk_benign_ignored",
                event_id=envelope.id,
                event_type=envelope.event_type,
                tenant_id=envelope.tenant_id,
                trace_id=envelope.trace_id,
                lane=envelope.lane.value,
                ignored_count=len(ignore_errors),
                total_items=len(results),
            )
        else:
            logger.info(
                "ip_worker_chunk_completed",
                event_id=envelope.id,
                event_type=envelope.event_type,
                tenant_id=envelope.tenant_id,
                trace_id=envelope.trace_id,
                lane=envelope.lane.value,
                total_items=len(results),
            )

        return ConsumerAction.ACK

    @staticmethod
    def map_outbound_response(
        response: DeliverOutboundRecordResponse,
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        """Maps a `DeliverOutboundRecordResponse` status to a `Result` with appropriate `FailureDisposition`."""
        if response.status is OutboundDispatchStatus.DELIVERED:
            return Result.ok(response)
        if response.status is OutboundDispatchStatus.RETRY_SCHEDULED:
            return Result.err(
                IpError(
                    code=IpErrorCode.EXTERNAL_API_ERROR,
                    message=response.error_message or "Outbound delivery scheduled for retry.",
                    details={
                        "outbound_record_id": response.outbound_record_id,
                        "retry_after_seconds": response.retry_after_seconds,
                    },
                    disposition=FailureDisposition.RETRY,
                )
            )
        return Result.err(
            IpError(
                code=IpErrorCode.EXTERNAL_API_ERROR,
                message=response.error_message or "Terminal outbound delivery failure.",
                details={
                    "outbound_record_id": response.outbound_record_id,
                    "response_status_code": response.response_status_code,
                },
                disposition=FailureDisposition.FAIL,
            )
        )


__all__ = ["IpWorkerResultDispositionHandler"]
