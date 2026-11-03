from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import structlog
from seedwork import generate_id
from seedwork.domain.exceptions import Result
from seedwork.id_registry import SystemIdPrefix

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.exceptions import EdiError, TraceNotFoundEdiError
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import ReplayCheckpoint
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class EdiStageReplayRequest:
    tenant_id: str
    trace_id: str
    actor: str


@dataclass(frozen=True, kw_only=True)
class EdiBulkStageReplayRequest:
    tenant_id: str
    trace_ids: tuple[str, ...]
    actor: str
    command_key: str | None = None


class EdiStageReplayProcessorPort(Protocol):
    """Polymorphic Strategy Port for EDI pipeline checkpoint replay."""

    async def replay(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiStageReplayRequest,
    ) -> Result[str, EdiError]: ...

    async def bulk_replay(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiBulkStageReplayRequest,
    ) -> Result[int, EdiError]: ...


class TransformStageReplayProcessor:
    """Immutable replay processor for the TRANSFORM checkpoint."""

    async def replay(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiStageReplayRequest,
    ) -> Result[str, EdiError]:
        original_msg = await uow.edi_messages.get_edi_message(
            request.trace_id, tenant_id=request.tenant_id
        )
        original_json = await uow.edi_jsons.get_edi_json(
            request.trace_id, tenant_id=request.tenant_id
        )

        logger.info(
            "replay_transform.lookup",
            tenant_id=request.tenant_id,
            trace_id=request.trace_id,
            found_msg=original_msg is not None,
            found_json=original_json is not None,
        )

        if not original_msg and not original_json:
            return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))

        direction = (
            original_msg.direction
            if original_msg
            else (original_json.direction if original_json else None)
        )

        logger.info(
            "replay_transform.started",
            tenant_id=request.tenant_id,
            trace_id=request.trace_id,
            actor=request.actor,
            direction=str(direction.value) if direction else None,
        )

        if direction == EdiDirection.INBOUND:
            source_msg = original_msg
            if not source_msg and original_json and original_json.parent_trace_id:
                source_msg = await uow.edi_messages.get_edi_message(
                    original_json.parent_trace_id, tenant_id=request.tenant_id
                )
            if not source_msg:
                return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))
            new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
            new_id = generate_id(DomainIdPrefix.EDI_MESSAGE.value)
            cloned_msg = source_msg.clone_for_transform_retry(new_id, new_trace_id)
            cloned_msg.mark_replay_triggered(request.actor)
            cloned_msg.request_transformation(
                trading_partner_id=cloned_msg.trading_partner_id,
                sender_id=cloned_msg.sender_id,
                receiver_id=cloned_msg.receiver_id,
                edi_message_id=cloned_msg.id,
            )
            await uow.edi_messages.save(cloned_msg)
            return Result.ok(new_trace_id)

        if direction == EdiDirection.OUTBOUND:
            source_json = original_json
            if not source_json and original_msg and original_msg.parent_trace_id:
                source_json = await uow.edi_jsons.get_edi_json(
                    original_msg.parent_trace_id, tenant_id=request.tenant_id
                )
            if not source_json:
                return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))
            new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
            new_id = generate_id(DomainIdPrefix.EDI_JSON.value)
            cloned_json = source_json.clone_for_transform_retry(new_id, new_trace_id)
            cloned_json.mark_replay_triggered(request.actor)
            cloned_json.request_transformation(
                trading_partner_id=cloned_json.trading_partner_id,
            )
            await uow.edi_jsons.save(cloned_json)
            return Result.ok(new_trace_id)

        return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))

    async def bulk_replay(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiBulkStageReplayRequest,
    ) -> Result[int, EdiError]:
        unique_trace_ids = tuple(dict.fromkeys(request.trace_ids))
        if not unique_trace_ids:
            return Result.ok(0)

        originals = await uow.edi_messages.get_edi_messages_by_traces(
            request.tenant_id, unique_trace_ids
        )
        if len(originals) != len(unique_trace_ids):
            found_ids = {m.trace_id for m in originals}
            missing = [tid for tid in unique_trace_ids if tid not in found_ids]
            return Result.fail(TraceNotFoundEdiError.for_trace_id(missing[0]))

        logger.info(
            "bulk_replay_transform.started",
            tenant_id=request.tenant_id,
            count=len(request.trace_ids),
            actor=request.actor,
        )

        for index, original in enumerate(originals):
            idempotency_key = (
                f"{request.command_key}_{index}"
                if request.command_key
                else generate_id(SystemIdPrefix.IDEMPOTENCY)
            )
            original.prepare_bulk_transform_replay(
                actor=request.actor,
                idempotency_key=idempotency_key,
            )
            await asyncio.sleep(0)

        await uow.edi_messages.save_all(originals)
        await uow.edi_messages.increment_replay_count(request.tenant_id, unique_trace_ids)
        await uow.edi_jsons.increment_replay_count(request.tenant_id, unique_trace_ids)
        return Result.ok(len(originals))


class DeliveryStageReplayProcessor:
    """Immutable replay processor for the DELIVERY checkpoint."""

    async def replay(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiStageReplayRequest,
    ) -> Result[str, EdiError]:
        original_msg = await uow.edi_messages.get_edi_message(
            request.trace_id, tenant_id=request.tenant_id
        )
        original_json = await uow.edi_jsons.get_edi_json(
            request.trace_id, tenant_id=request.tenant_id
        )

        logger.info(
            "replay_deliver.lookup",
            tenant_id=request.tenant_id,
            trace_id=request.trace_id,
            found_msg=original_msg is not None,
            found_json=original_json is not None,
        )

        if not original_msg and not original_json:
            return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))

        direction = (
            original_msg.direction
            if original_msg
            else (original_json.direction if original_json else None)
        )

        logger.info(
            "replay_deliver.started",
            tenant_id=request.tenant_id,
            trace_id=request.trace_id,
            actor=request.actor,
            direction=str(direction.value) if direction else None,
        )

        if direction == EdiDirection.INBOUND:
            return await self._replay_inbound(uow, request, original_msg)
        if direction == EdiDirection.OUTBOUND:
            return await self._replay_outbound(uow, request, original_msg, original_json)
        return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))

    async def _replay_inbound(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiStageReplayRequest,
        original_msg: EdiMessage | None,
    ) -> Result[str, EdiError]:
        source_jsons = await uow.edi_jsons.get_edi_jsons_by_trace_id(
            request.trace_id, request.tenant_id
        )
        if not source_jsons and original_msg and original_msg.parent_trace_id:
            source_jsons = await uow.edi_jsons.get_edi_jsons_by_trace_id(
                original_msg.parent_trace_id, request.tenant_id
            )
        if not source_jsons:
            return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))

        new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
        for index, source_json in enumerate(source_jsons):
            new_id = generate_id(DomainIdPrefix.EDI_JSON.value)
            cloned_json = source_json.clone_for_delivery_retry(new_id, new_trace_id)
            cloned_json.mark_replay_triggered(request.actor)
            if index == 0:
                cloned_json.request_delivery(
                    trading_partner_id=cloned_json.trading_partner_id,
                    transaction_type=cloned_json.transaction_type,
                )
            await uow.edi_jsons.save(cloned_json)
        return Result.ok(new_trace_id)

    async def _replay_outbound(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiStageReplayRequest,
        original_msg: EdiMessage | None,
        original_json: EdiJson | None,
    ) -> Result[str, EdiError]:
        source_msg = original_msg
        if not source_msg and original_json and original_json.parent_trace_id:
            source_msg = await uow.edi_messages.get_edi_message(
                original_json.parent_trace_id, tenant_id=request.tenant_id
            )
        if not source_msg:
            return Result.fail(TraceNotFoundEdiError.for_trace_id(request.trace_id))

        new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
        new_id = generate_id(DomainIdPrefix.EDI_MESSAGE.value)
        cloned_msg = source_msg.clone_for_delivery_retry(new_id, new_trace_id)
        cloned_msg.mark_replay_triggered(request.actor)
        cloned_msg.request_delivery(
            trading_partner_id=cloned_msg.trading_partner_id,
            transaction_type=cloned_msg.transaction_type,
        )
        await uow.edi_messages.save(cloned_msg)
        return Result.ok(new_trace_id)

    async def bulk_replay(
        self,
        uow: DataPlaneUnitOfWorkPort,
        request: EdiBulkStageReplayRequest,
    ) -> Result[int, EdiError]:
        unique_trace_ids = tuple(dict.fromkeys(request.trace_ids))
        if not unique_trace_ids:
            return Result.ok(0)

        originals = await uow.edi_messages.get_edi_messages_by_traces(
            request.tenant_id, unique_trace_ids
        )
        if len(originals) != len(unique_trace_ids):
            found_ids = {m.trace_id for m in originals}
            missing = [tid for tid in unique_trace_ids if tid not in found_ids]
            return Result.fail(TraceNotFoundEdiError.for_trace_id(missing[0]))

        logger.info(
            "bulk_replay_deliver.started",
            tenant_id=request.tenant_id,
            count=len(request.trace_ids),
            actor=request.actor,
        )

        for index, original in enumerate(originals):
            idempotency_key = (
                f"{request.command_key}_{index}"
                if request.command_key
                else generate_id(SystemIdPrefix.IDEMPOTENCY)
            )
            original.prepare_bulk_delivery_replay(
                actor=request.actor,
                idempotency_key=idempotency_key,
            )
            await asyncio.sleep(0)

        await uow.edi_messages.save_all(originals)
        await uow.edi_messages.increment_replay_count(request.tenant_id, unique_trace_ids)
        return Result.ok(len(originals))


def build_default_edi_stage_replay_processors() -> Mapping[
    ReplayCheckpoint, EdiStageReplayProcessorPort
]:
    """Composition factory assembling polymorphic EDI stage replay processors."""
    return {
        ReplayCheckpoint.TRANSFORM: TransformStageReplayProcessor(),
        ReplayCheckpoint.DELIVERY: DeliveryStageReplayProcessor(),
    }


__all__ = [
    "DeliveryStageReplayProcessor",
    "EdiBulkStageReplayRequest",
    "EdiStageReplayProcessorPort",
    "EdiStageReplayRequest",
    "TransformStageReplayProcessor",
    "build_default_edi_stage_replay_processors",
]
