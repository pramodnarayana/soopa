from __future__ import annotations

import json
from dataclasses import dataclass

import structlog
from seedwork import generate_id
from seedwork.domain.exceptions import Result
from seedwork.id_registry import SystemIdPrefix

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.exceptions import (
    EdiError,
    InvalidPayloadEdiError,
    TraceNotFoundEdiError,
)
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ModifyAndReplayCommand:
    tenant_id: str
    original_trace_id: str
    modified_payload: str
    actor: str = "USER"


class ModifyAndReplayUseCase:
    """
    Manual Intervention (Modify & Replay).
    Clones the target stage aggregate with operator-corrected payload, records audit
    trace events on both parent and child aggregates, and commits via the Transactional Outbox.
    """

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: ModifyAndReplayCommand) -> Result[str, EdiError]:
        original_msg = await self._uow.edi_messages.get_edi_message(
            command.original_trace_id, tenant_id=command.tenant_id
        )

        new_trace_id = generate_id(SystemIdPrefix.TRACE)

        logger.info(
            "modify_and_replay.started",
            tenant_id=command.tenant_id,
            original_trace_id=command.original_trace_id,
            new_trace_id=new_trace_id,
            actor=command.actor,
        )

        if original_msg is not None:
            created_trace_id = await self._handle_edi_message(
                command=command,
                new_trace_id=new_trace_id,
                original=original_msg,
            )
            return Result.ok(created_trace_id)

        original_json = await self._uow.edi_jsons.get_edi_json(
            command.original_trace_id, tenant_id=command.tenant_id
        )
        if original_json is not None:
            return await self._handle_edi_json(
                command=command,
                new_trace_id=new_trace_id,
                original=original_json,
            )

        not_found = TraceNotFoundEdiError.for_trace_id(command.original_trace_id)
        logger.error(
            "modify_and_replay.not_found",
            tenant_id=command.tenant_id,
            original_trace_id=command.original_trace_id,
            error_code=not_found.code,
        )
        return Result.fail(not_found)

    async def _handle_edi_message(
        self,
        *,
        command: ModifyAndReplayCommand,
        new_trace_id: str,
        original: EdiMessage,
    ) -> str:
        new_msg = original.clone_with_modified_payload(
            new_id=generate_id(DomainIdPrefix.EDI_MESSAGE.value),
            new_trace_id=new_trace_id,
            modified_payload=command.modified_payload,
            actor=command.actor,
        )
        await self._uow.edi_messages.save(new_msg)
        await self._uow.edi_messages.flush_events(original)
        await self._uow.commit()
        logger.info(
            "modify_and_replay.completed",
            tenant_id=command.tenant_id,
            original_trace_id=command.original_trace_id,
            new_trace_id=new_trace_id,
        )
        return new_trace_id

    async def _handle_edi_json(
        self,
        *,
        command: ModifyAndReplayCommand,
        new_trace_id: str,
        original: EdiJson,
    ) -> Result[str, EdiError]:
        try:
            parsed_payload = json.loads(command.modified_payload)
        except json.JSONDecodeError as e:
            bad_payload = InvalidPayloadEdiError.with_message(
                f"Invalid JSON payload provided for correction: {e}",
                details={"original_trace_id": command.original_trace_id},
            )
            logger.error(
                "modify_and_replay.invalid_json_payload",
                tenant_id=command.tenant_id,
                original_trace_id=command.original_trace_id,
                error_code=bad_payload.code,
                reason=str(e),
            )
            return Result.fail(bad_payload)

        new_json = original.clone_with_modified_payload(
            new_id=generate_id(DomainIdPrefix.EDI_JSON.value),
            new_trace_id=new_trace_id,
            parsed_payload=parsed_payload,
            actor=command.actor,
        )
        await self._uow.edi_jsons.save(new_json)
        await self._uow.edi_jsons.flush_events(original)
        await self._uow.commit()
        logger.info(
            "modify_and_replay.completed",
            tenant_id=command.tenant_id,
            original_trace_id=command.original_trace_id,
            new_trace_id=new_trace_id,
        )
        return Result.ok(new_trace_id)
