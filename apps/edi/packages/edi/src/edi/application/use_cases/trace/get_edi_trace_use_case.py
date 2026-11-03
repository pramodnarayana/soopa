from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from edi.application.responses import ApiGatewayDTO, EdiJsonDTO, EdiMessageDTO, EdiTraceDTO
from edi.domain.exceptions import EdiError, TraceNotFoundEdiError
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class GetEdiTraceQuery:
    tenant_id: str
    trace_id: str


class GetEdiTraceUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def _hydrate_edi_message(
        self, tenant_id: str, edi_jsons: list[EdiJson]
    ) -> EdiMessage | None:
        if not edi_jsons:
            return None
        curr_parent_id = edi_jsons[0].parent_trace_id
        visited: set[str] = set()
        for _ in range(10):
            if not curr_parent_id or curr_parent_id in visited:
                break
            visited.add(curr_parent_id)
            parent_msg = await self._uow.edi_messages.get_edi_message(
                curr_parent_id, tenant_id=tenant_id
            )
            if parent_msg is not None:
                return parent_msg
            parent_jsons = await self._uow.edi_jsons.get_edi_jsons_by_trace_id(
                curr_parent_id, tenant_id=tenant_id
            )
            curr_parent_id = (
                parent_jsons[0].parent_trace_id
                if (parent_jsons and parent_jsons[0].parent_trace_id)
                else None
            )

        if edi_jsons[0].original_trace_id and edi_jsons[0].original_trace_id not in visited:
            return await self._uow.edi_messages.get_edi_message(
                edi_jsons[0].original_trace_id, tenant_id=tenant_id
            )
        return None

    async def _hydrate_edi_jsons(
        self, tenant_id: str, edi_message: EdiMessage | None
    ) -> list[EdiJson]:
        if edi_message is None:
            return []
        curr_parent_id = edi_message.parent_trace_id
        visited: set[str] = set()
        for _ in range(10):
            if not curr_parent_id or curr_parent_id in visited:
                break
            visited.add(curr_parent_id)
            parent_jsons = await self._uow.edi_jsons.get_edi_jsons_by_trace_id(
                curr_parent_id, tenant_id=tenant_id
            )
            if parent_jsons:
                return parent_jsons
            parent_msg = await self._uow.edi_messages.get_edi_message(
                curr_parent_id, tenant_id=tenant_id
            )
            curr_parent_id = (
                parent_msg.parent_trace_id if (parent_msg and parent_msg.parent_trace_id) else None
            )

        if edi_message.original_trace_id and edi_message.original_trace_id not in visited:
            return await self._uow.edi_jsons.get_edi_jsons_by_trace_id(
                edi_message.original_trace_id, tenant_id=tenant_id
            )
        return []

    async def execute(self, query: GetEdiTraceQuery) -> Result[EdiTraceDTO, EdiError]:
        """
        Assembles the composite EDI trace waterfall from the UoW stage repositories.
        Walks parent_trace_id upstream if an initial stage was not duplicated on replay.
        """
        edi_message = await self._uow.edi_messages.get_edi_message(
            query.trace_id, tenant_id=query.tenant_id
        )
        edi_jsons = await self._uow.edi_jsons.get_edi_jsons_by_trace_id(
            query.trace_id, tenant_id=query.tenant_id
        )
        api_gateways = await self._uow.api_gateway_receipts.get_api_gateways_by_trace_id(
            query.tenant_id, query.trace_id
        )

        if edi_message is None and edi_jsons:
            edi_message = await self._hydrate_edi_message(query.tenant_id, edi_jsons)

        if not edi_jsons and edi_message is not None:
            edi_jsons = await self._hydrate_edi_jsons(query.tenant_id, edi_message)

        logger.info(
            "get_edi_trace.assembled",
            tenant_id=query.tenant_id,
            trace_id=query.trace_id,
            edi_message_found=edi_message is not None,
            edi_json_count=len(edi_jsons),
            api_gateway_count=len(api_gateways),
        )

        if edi_message is None and not edi_jsons and not api_gateways:
            not_found = TraceNotFoundEdiError.for_trace_id(query.trace_id)
            logger.error(
                "get_edi_trace.not_found",
                tenant_id=query.tenant_id,
                trace_id=query.trace_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        return Result.ok(
            EdiTraceDTO(
                edi_message=EdiMessageDTO.from_domain(edi_message) if edi_message else None,
                edi_jsons=tuple(EdiJsonDTO.from_domain(j) for j in edi_jsons),
                api_gateways=tuple(ApiGatewayDTO.from_domain(r) for r in api_gateways),
            )
        )
