from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonValue

from edi.application.responses import EdiJsonDTO, EdiMessageDTO
from edi.domain.exceptions import EdiError
from edi.domain.transaction.stage_filter import StageFilterCriterion, StageFilterTarget
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class RawStageFilterInput:
    field: str
    operator: str = "eq"
    value: JsonValue = None


@dataclass(frozen=True, kw_only=True)
class ExploreEdiMessagesQuery:
    tenant_id: str
    filters: Sequence[RawStageFilterInput] = ()
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class ExploreEdiJsonQuery:
    tenant_id: str
    filters: Sequence[RawStageFilterInput] = ()
    limit: int = 50
    offset: int = 0


class ExploreEdiStageUseCase:
    """Validates typed stage filter criteria and queries EDI stage ledgers via the UoW."""

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def explore_messages(
        self, query: ExploreEdiMessagesQuery
    ) -> Result[Sequence[EdiMessageDTO], EdiError]:
        validation = StageFilterCriterion.validate_all(
            [(item.field, item.operator, item.value) for item in query.filters],
            target=StageFilterTarget.EDI_MESSAGE,
        )
        if validation.is_err:
            err = validation.unwrap_err()
            logger.error(
                "explore_edi_messages.invalid_filters",
                tenant_id=query.tenant_id,
                error_code=err.code,
                reason=err.message,
            )
            return Result.fail(err)

        records = await self._uow.edi_messages.explorer_list_edi_messages(
            tenant_id=query.tenant_id,
            filters=validation.unwrap(),
            limit=query.limit,
            offset=query.offset,
        )
        return Result.ok([EdiMessageDTO.from_domain(msg) for msg in records])

    async def explore_json(
        self, query: ExploreEdiJsonQuery
    ) -> Result[Sequence[EdiJsonDTO], EdiError]:
        validation = StageFilterCriterion.validate_all(
            [(item.field, item.operator, item.value) for item in query.filters],
            target=StageFilterTarget.EDI_JSON,
        )
        if validation.is_err:
            err = validation.unwrap_err()
            logger.error(
                "explore_edi_json.invalid_filters",
                tenant_id=query.tenant_id,
                error_code=err.code,
                reason=err.message,
            )
            return Result.fail(err)

        records = await self._uow.edi_jsons.explorer_list_edi_json(
            tenant_id=query.tenant_id,
            filters=validation.unwrap(),
            limit=query.limit,
            offset=query.offset,
        )
        return Result.ok([EdiJsonDTO.from_domain(record) for record in records])
