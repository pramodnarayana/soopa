import structlog

from edi.application.dtos.trace import EdiTraceDTO
from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class GetEdiTraceUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def _hydrate_edi_message(
        self, tenant_id: str, edi_jsons: list[EdiJsonDTO]
    ) -> EdiMessageDTO | None:
        if not edi_jsons:
            return None
        curr_parent_id = edi_jsons[0].parent_trace_id
        visited: set[str] = set()
        for _ in range(10):
            if not curr_parent_id or curr_parent_id in visited:
                break
            visited.add(curr_parent_id)
            parent_msg = await self.uow.transactions.get_edi_message_dto(tenant_id, curr_parent_id)
            if parent_msg is not None:
                return parent_msg
            parent_jsons = await self.uow.transactions.get_edi_json_dtos_by_trace_id(
                tenant_id, curr_parent_id
            )
            curr_parent_id = (
                parent_jsons[0].parent_trace_id
                if (parent_jsons and parent_jsons[0].parent_trace_id)
                else None
            )

        if edi_jsons[0].original_trace_id and edi_jsons[0].original_trace_id not in visited:
            return await self.uow.transactions.get_edi_message_dto(
                tenant_id, edi_jsons[0].original_trace_id
            )
        return None

    async def _hydrate_edi_jsons(
        self, tenant_id: str, edi_message: EdiMessageDTO | None
    ) -> list[EdiJsonDTO]:
        if edi_message is None:
            return []
        curr_parent_id = edi_message.parent_trace_id
        visited: set[str] = set()
        for _ in range(10):
            if not curr_parent_id or curr_parent_id in visited:
                break
            visited.add(curr_parent_id)
            parent_jsons = await self.uow.transactions.get_edi_json_dtos_by_trace_id(
                tenant_id, curr_parent_id
            )
            if parent_jsons:
                return parent_jsons
            parent_msg = await self.uow.transactions.get_edi_message_dto(tenant_id, curr_parent_id)
            curr_parent_id = (
                parent_msg.parent_trace_id if (parent_msg and parent_msg.parent_trace_id) else None
            )

        if edi_message.original_trace_id and edi_message.original_trace_id not in visited:
            return await self.uow.transactions.get_edi_json_dtos_by_trace_id(
                tenant_id, edi_message.original_trace_id
            )
        return []

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

        if edi_message is None and edi_jsons:
            edi_message = await self._hydrate_edi_message(tenant_id, edi_jsons)

        if not edi_jsons and edi_message is not None:
            edi_jsons = await self._hydrate_edi_jsons(tenant_id, edi_message)

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
