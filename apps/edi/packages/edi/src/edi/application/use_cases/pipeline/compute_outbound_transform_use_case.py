import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import structlog
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from seedwork.utils import generate_deterministic_id, generate_id

from edi.domain.enums import (
    EdiDirection,
    EdiStandard,
    PipelineEventType,
)
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.domain.types import AstNode
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ComputeOutboundTransformCommand:
    trace_id: str
    tenant_id: str
    idempotency_key: str
    standard: str = EdiStandard.X12.value
    # transaction_type has NO default — callers must supply it explicitly.
    # An absent or sentinel value from the SQS payload must be caught by the
    # dispatcher before constructing this command, not silently swallowed here.
    transaction_type: str
    route_config: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.trace_id or not self.trace_id.strip():
            raise ValueError("Required field 'trace_id' is missing or empty")
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("Required field 'tenant_id' is missing or empty")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("Required field 'idempotency_key' is missing or empty")
        if self.route_config is None:
            raise ValueError("Required field 'route_config' is missing")
        if not self.transaction_type or not self.transaction_type.strip():
            raise ValueError("Required field 'transaction_type' is missing or empty")


class ComputeOutboundTransformUseCase:
    """
    Application Use Case running exclusively in the Compute Worker.
    Executes heavy JSON to EDI transformations.
    """

    def __init__(
        self,
        transformer: TransformerPort,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
    ) -> None:
        self.transformer = transformer
        self.uow_factory = uow_factory

    def _determine_connection_type(self, route_config: dict[str, Any]) -> str:
        # Note: outbound_route is technically needed to perfectly determine this,
        # but the orchestrator passed it via route_config if needed,
        connection_type = route_config.get("connection_type")
        if not connection_type:
            raise ValueError("Unresolvable connection type")
        return str(connection_type)

    async def _save_edi_message(
        self,
        uow: DataPlaneUnitOfWorkPort,
        edi_json: Any,
        trace_id: str,
        edi_str: str,
        standard: str,
        transaction_type: str,
        connection_type: str,
        route_config: dict[str, Any],
        trading_partner_id: str | None,
    ) -> None:
        isa_sender_id = str(route_config.get("isa_sender_id") or "")
        isa_receiver_id = str(route_config.get("isa_receiver_id") or "")
        gs_sender_id_raw = route_config.get("gs_sender_id")
        gs_sender_id = str(gs_sender_id_raw) if gs_sender_id_raw is not None else None
        gs_receiver_id_raw = route_config.get("gs_receiver_id")
        gs_receiver_id = str(gs_receiver_id_raw) if gs_receiver_id_raw is not None else None

        if not trading_partner_id:
            business_metadata = edi_json.business_metadata or {}
            routing_meta = business_metadata.get("_routing")
            if isinstance(routing_meta, dict):
                tp_id = routing_meta.get("trading_partner_id")
                trading_partner_id = str(tp_id) if tp_id else None

        existing_msg = await uow.transactions.get_edi_message(trace_id)
        if existing_msg:
            edi_msg = existing_msg
            edi_msg.mark_outbound_pending_delivery(
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=transaction_type,
                connection_type=connection_type,
                sender_id=isa_sender_id,
                receiver_id=isa_receiver_id,
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                trading_partner_id=trading_partner_id,
            )
        else:
            edi_msg = EdiMessageDomainModel.create_outbound(
                id=generate_id(DomainIdPrefix.EDI_MESSAGE.value),
                trace_id=trace_id,
                tenant_id=edi_json.tenant_id or "",
                replay_count=edi_json.replay_count,
                parent_trace_id=edi_json.parent_trace_id,
                original_trace_id=edi_json.original_trace_id,
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=transaction_type,
                connection_type=connection_type,
                sender_id=isa_sender_id,
                receiver_id=isa_receiver_id,
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                trading_partner_id=trading_partner_id,
            )
        await uow.transactions.save(edi_msg)

    async def execute(self, command: ComputeOutboundTransformCommand) -> None:
        """Transforms an outbound JSON payload to X12 EDI."""
        trace_id = command.trace_id.strip()
        standard = command.standard
        transaction_type = command.transaction_type
        route_config = command.route_config

        logger.info(
            "compute_outbound_transform.started",
            trace_id=trace_id,
            standard=standard,
            transaction_type=transaction_type,
        )

        async with self.uow_factory() as uow, uow:
            edi_json = await uow.transactions.get_edi_json(trace_id)
            if not edi_json:
                logger.warning("compute_outbound_transform.edi_json_not_found", trace_id=trace_id)
                raise TransactionNotFoundError(trace_id)

            json_payload = edi_json.payload
            if not json_payload or not (
                isinstance(json_payload, dict)
                or (
                    isinstance(json_payload, list)
                    and all(isinstance(node, dict) for node in json_payload)
                )
            ):
                raise TransactionNotFoundError(trace_id)

            resolved_transaction_type = command.transaction_type
        try:
            async with self.uow_factory() as uow, uow:
                # 0. Idempotency Check — use per-event idempotency_key, NOT trace_id.
                # trace_id is stable across replays; using it would cause replays to be
                # silently dropped as duplicates.
                is_new = await uow.record_idempotency(command.tenant_id, command.idempotency_key)
                if not is_new:
                    logger.info("compute_outbound_transform.duplicate_skipped", trace_id=trace_id)
                    return

                edi_json = await uow.transactions.get_edi_json(trace_id)
                if not edi_json:
                    logger.warning(
                        "compute_outbound_transform.edi_json_not_found", trace_id=trace_id
                    )
                    raise TransactionNotFoundError(trace_id)

                json_payload = edi_json.payload
                if not json_payload or not (
                    isinstance(json_payload, dict)
                    or (
                        isinstance(json_payload, list)
                        and all(isinstance(node, dict) for node in json_payload)
                    )
                ):
                    raise TransactionNotFoundError(trace_id)

                resolved_transaction_type = command.transaction_type

                logger.info(
                    "compute_outbound_transform.resolved",
                    trace_id=trace_id,
                    transaction_type=resolved_transaction_type,
                    standard=standard,
                )

                # 1. Transform
                raw_edi_bytes = await self.transformer.transform_json_to_edi(
                    payload=cast(AstNode | list[AstNode], json_payload),
                    standard=standard,
                    transaction_type=resolved_transaction_type,
                    route_config=route_config,
                )

                edi_str = raw_edi_bytes.decode("utf-8")
                connection_type = self._determine_connection_type(route_config)

                trading_partner_id = edi_json.trading_partner_id

                # 2. Save EdiMessage
                await self._save_edi_message(
                    uow=uow,
                    edi_json=edi_json,
                    trace_id=trace_id,
                    edi_str=edi_str,
                    standard=standard,
                    transaction_type=resolved_transaction_type,
                    connection_type=connection_type,
                    route_config=route_config,
                    trading_partner_id=trading_partner_id,
                )

                isa_sender_id = str(route_config.get("isa_sender_id") or "")
                isa_receiver_id = str(route_config.get("isa_receiver_id") or "")
                gs_sender_id_raw = route_config.get("gs_sender_id")
                gs_sender_id = str(gs_sender_id_raw) if gs_sender_id_raw is not None else None
                gs_receiver_id_raw = route_config.get("gs_receiver_id")
                gs_receiver_id = str(gs_receiver_id_raw) if gs_receiver_id_raw is not None else None
                logger.info("compute_outbound_transform.edi_message_saved", trace_id=trace_id)

                # 3. Dispatch TRANSFORMATION_SUCCESSFUL
                transform_successful_key = generate_deterministic_id(
                    SystemIdPrefix.IDEMPOTENCY, trace_id, "TRANSFORMATION_SUCCESSFUL"
                )
                await uow.outbox.append_event(
                    idempotency_key=transform_successful_key,
                    event_type=PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
                    payload={
                        "trace_id": trace_id,
                        "direction": EdiDirection.OUTBOUND.value,
                        "trading_partner_id": trading_partner_id,
                        "standard": standard,
                        "isa_sender_id": isa_sender_id,
                        "isa_receiver_id": isa_receiver_id,
                        "gs_sender_id": gs_sender_id,
                        "gs_receiver_id": gs_receiver_id,
                    },
                )

                await uow.commit()

            logger.info("compute_outbound_transform.completed", trace_id=trace_id)
        except Exception as e:
            logger.exception("compute_outbound_transform.failed", trace_id=trace_id, error=str(e))
            async with self.uow_factory() as failure_uow, failure_uow:
                edi_json_fallback = await failure_uow.transactions.get_edi_json(trace_id)
                if edi_json_fallback:
                    event_key = generate_deterministic_id(
                        SystemIdPrefix.IDEMPOTENCY, trace_id, "TRANSFORMATION_FAILED"
                    )
                    await failure_uow.outbox.append_event(
                        idempotency_key=event_key,
                        event_type=PipelineEventType.TRANSFORMATION_FAILED.value,
                        payload={
                            "trace_id": trace_id,
                            "direction": EdiDirection.OUTBOUND.value,
                            "tenant_id": edi_json_fallback.tenant_id or "",
                            "failure_reason": str(e),
                        },
                    )
                    await failure_uow.commit()
            raise
