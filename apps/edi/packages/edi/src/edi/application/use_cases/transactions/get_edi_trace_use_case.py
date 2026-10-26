import structlog

from edi.application.dtos.trace import EdiTraceDTO
from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class GetEdiTraceUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def get_edi_trace(
        self, tenant_id: str, trace_id: str, _routing_resolver: object | None = None
    ) -> EdiTraceDTO:
        """
        Assembles the composite EDI trace waterfall from the UoW stage repositories.
        Walks parent_trace_id upstream if an initial stage was not duplicated on replay.
        """
        edi_message = await self.uow.transactions.get_edi_message_dto(tenant_id, trace_id)
        edi_jsons = await self.uow.transactions.get_edi_json_dtos_by_trace_id(tenant_id, trace_id)
        api_gateways = await self.uow.api_gateway_transactions.get_api_gateways_by_trace_id(
            tenant_id, trace_id
        )

        # Enterprise Hydration: If an upstream stage is missing on this trace attempt
        # (e.g. Delivery retry where Stage 1 was not duplicated), hydrate it from parent_trace_id.
        if edi_message is None and edi_jsons and edi_jsons[0].parent_trace_id:
            edi_message = await self.uow.transactions.get_edi_message_dto(
                tenant_id,
                edi_jsons[0].parent_trace_id,
            )

        if not edi_jsons and edi_message is not None and edi_message.parent_trace_id:
            edi_jsons = await self.uow.transactions.get_edi_json_dtos_by_trace_id(
                tenant_id,
                edi_message.parent_trace_id,
            )

        logger.info(
            "get_edi_trace.assembled",
            tenant_id=tenant_id,
            trace_id=trace_id,
            edi_message_found=edi_message is not None,
            edi_json_count=len(edi_jsons),
            api_gateway_count=len(api_gateways),
        )

        # A trace is valid if ANY of its composite parts exist. Outbound replay creates
        # EdiJson first; the EdiMessage is written asynchronously by the transform worker.
        # Raising 404 solely on missing EdiMessage would break the race window.
        if edi_message is None and not edi_jsons and not api_gateways:
            raise TransactionNotFoundError(trace_id=trace_id)

        return EdiTraceDTO(
            edi_message=edi_message,
            edi_jsons=edi_jsons,
            api_gateways=api_gateways,
        )
