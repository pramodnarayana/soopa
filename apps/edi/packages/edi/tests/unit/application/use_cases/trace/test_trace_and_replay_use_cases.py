"""Application use-case unit tests for EDI Trace Waterfall, Lineage, Stage Listings, Explorer, and Stage Replay."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

import pytest
from database.outbox_serializer import serialize_domain_event
from seedwork.events import EventEnvelope
from seedwork.utils import generate_id
from strace.testing import InMemoryTraceRepository

from edi.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageCommand,
    BulkReplayStageUseCase,
)
from edi.application.use_cases.replay.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayUseCase,
)
from edi.application.use_cases.replay.replay_stage_use_case import (
    ReplayStageCommand,
    ReplayStageUseCase,
)
from edi.application.use_cases.replay.stage_replay_processor import (
    build_default_edi_stage_replay_processors,
)
from edi.application.use_cases.trace.explore_edi_stage_use_case import (
    ExploreEdiJsonQuery,
    ExploreEdiMessagesQuery,
    ExploreEdiStageUseCase,
    RawStageFilterInput,
)
from edi.application.use_cases.trace.get_edi_trace_lineage_use_case import (
    GetEdiTraceLineageQuery,
    GetEdiTraceLineageUseCase,
)
from edi.application.use_cases.trace.get_edi_trace_use_case import (
    GetEdiTraceQuery,
    GetEdiTraceUseCase,
)
from edi.application.use_cases.trace.list_edi_json_use_case import (
    ListEdiJsonQuery,
    ListEdiJsonUseCase,
)
from edi.application.use_cases.trace.list_edi_messages_use_case import (
    ListEdiMessagesQuery,
    ListEdiMessagesUseCase,
)
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiTraceEventType
from edi.domain.exceptions import EdiErrorCode
from edi.domain.routing.enums import Direction, EdiDirection
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus, RecordStatus, ReplayCheckpoint
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt
from edi.domain.transaction.stage_filter import StageFilterCriterion
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


async def _drain_events(
    model: EdiMessage | EdiJson,
    outbox_events: list[dict[str, object]],
    trace_repo: InMemoryTraceRepository,
) -> list[EventEnvelope]:
    envelopes: list[EventEnvelope] = []
    for e in model.domain_events:
        event_type = e.event_name
        payload = serialize_domain_event(e)
        key = e.idempotency_key
        env = EventEnvelope(
            id=str(uuid.uuid4()),
            source="test",
            tenant_id=model.tenant_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=key,
        )
        envelopes.append(env)
        outbox_events.append(
            {
                "tenant_id": model.tenant_id,
                "event_type": event_type,
                "payload": payload,
                "key": key,
            }
        )
    for t_event in model.trace_events:
        await trace_repo.save_trace_event(t_event)
    model.clear_domain_events()
    model.clear_trace_events()
    return envelopes


class FakeEdiMessageRepository:
    def __init__(
        self,
        outbox_events: list[dict[str, object]],
        trace_repo: InMemoryTraceRepository,
    ) -> None:
        self._models: dict[str, EdiMessage] = {}
        self._ordered_list: list[EdiMessage] = []
        self.outbox_events = outbox_events
        self._trace_repo = trace_repo

    def seed(self, model: EdiMessage) -> None:
        self._models[model.id] = model
        self._ordered_list.append(model)

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessage | None:
        for model in self._models.values():
            if model.trace_id == trace_id and (tenant_id is None or model.tenant_id == tenant_id):
                return model
        return None

    async def get_edi_messages_by_traces(
        self, tenant_id: str, trace_ids: Sequence[str]
    ) -> Sequence[EdiMessage]:
        return [
            m for m in self._models.values() if m.tenant_id == tenant_id and m.trace_id in trace_ids
        ]

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessage]:
        _ = (partner_id, transaction_type, direction)
        items = [m for m in self._ordered_list if m.tenant_id == tenant_id]
        return items[offset : offset + limit]

    async def explorer_list_edi_messages(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiMessage]:
        results: list[EdiMessage] = []
        for m in self._models.values():
            if m.tenant_id != tenant_id:
                continue
            matches = True
            for criterion in filters:
                if (
                    (
                        criterion.field == "original_trace_id"
                        and (
                            m.original_trace_id != criterion.value and m.trace_id != criterion.value
                        )
                    )
                    or (
                        criterion.field == "direction"
                        and (m.direction.value if m.direction else None) != criterion.value
                    )
                    or (criterion.field == "sender_id" and m.sender_id != criterion.value)
                ):
                    matches = False
            if matches:
                results.append(m)
        return results[offset : offset + limit]

    async def save(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]:
        self._models[aggregate.id] = aggregate
        return await _drain_events(aggregate, self.outbox_events, self._trace_repo)

    async def flush_events(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]:
        return await _drain_events(aggregate, self.outbox_events, self._trace_repo)

    async def save_all(self, aggregates: Sequence[EdiMessage]) -> Sequence[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        for agg in aggregates:
            envelopes.extend(await self.save(agg))
        return envelopes

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None:
        for model in self._models.values():
            if model.tenant_id == tenant_id and model.trace_id in trace_ids:
                model.replay_count += 1


class FakeEdiJsonRepository:
    def __init__(
        self,
        outbox_events: list[dict[str, object]],
        trace_repo: InMemoryTraceRepository,
    ) -> None:
        self._models: dict[str, EdiJson] = {}
        self.outbox_events = outbox_events
        self._trace_repo = trace_repo

    def seed(self, model: EdiJson) -> None:
        self._models[model.id] = model

    async def get_edi_json(self, trace_id: str, tenant_id: str | None = None) -> EdiJson | None:
        for model in self._models.values():
            if model.trace_id == trace_id and (tenant_id is None or model.tenant_id == tenant_id):
                return model
        return None

    async def get_edi_jsons_by_trace_id(
        self, trace_id: str, tenant_id: str | None = None
    ) -> list[EdiJson]:
        return [
            model
            for model in self._models.values()
            if model.trace_id == trace_id and (tenant_id is None or model.tenant_id == tenant_id)
        ]

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJson]:
        return [
            j
            for j in self._models.values()
            if j.tenant_id == tenant_id
            and j.business_metadata is not None
            and j.business_metadata.get(key) == value
        ]

    async def explorer_list_edi_json(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiJson]:
        results: list[EdiJson] = []
        for j in self._models.values():
            if j.tenant_id != tenant_id:
                continue
            matches = True
            for criterion in filters:
                if (
                    criterion.field == "original_trace_id"
                    and (j.original_trace_id != criterion.value and j.trace_id != criterion.value)
                ) or (
                    criterion.field == "direction"
                    and (j.direction.value if j.direction else None) != criterion.value
                ):
                    matches = False
            if matches:
                results.append(j)
        return results[offset : offset + limit]

    async def save(self, aggregate: EdiJson) -> Sequence[EventEnvelope]:
        self._models[aggregate.id] = aggregate
        return await _drain_events(aggregate, self.outbox_events, self._trace_repo)

    async def flush_events(self, aggregate: EdiJson) -> Sequence[EventEnvelope]:
        return await _drain_events(aggregate, self.outbox_events, self._trace_repo)

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None:
        for model in self._models.values():
            if model.tenant_id == tenant_id and model.trace_id in trace_ids:
                model.replay_count += 1


class FakeApiGatewayRepository:
    def __init__(self) -> None:
        self._receipts: dict[str, list[ApiGatewayReceipt]] = {}

    def seed(self, receipt: ApiGatewayReceipt) -> None:
        key = f"{receipt.tenant_id}:{receipt.trace_id}"
        self._receipts.setdefault(key, []).append(receipt)

    async def get_api_gateways_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[ApiGatewayReceipt]:
        return list(self._receipts.get(f"{tenant_id}:{trace_id}", []))


class FakeDataPlaneUnitOfWork:
    def __init__(self, trace_repo: InMemoryTraceRepository) -> None:
        self.outbox_events: list[dict[str, object]] = []
        self.traces = trace_repo
        self.edi_messages = FakeEdiMessageRepository(self.outbox_events, trace_repo)
        self.edi_jsons = FakeEdiJsonRepository(self.outbox_events, trace_repo)
        self.api_gateway_receipts = FakeApiGatewayRepository()
        self.committed = False

    async def __aenter__(self) -> FakeDataPlaneUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        _ = args

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class TestGetEdiTraceUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo)
        self.use_case = GetEdiTraceUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_not_found_when_trace_missing(self) -> None:
        res = await self.use_case.execute(
            GetEdiTraceQuery(tenant_id=self.tenant_id, trace_id="missing-trace")
        )
        assert res.is_err
        assert res.unwrap_err().code == EdiErrorCode.TRACE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_returns_trace_result(self) -> None:
        now = datetime.now(UTC)
        msg = EdiMessage(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="trace-ok",
            connection_type="AS2",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
            created_at=now,
            updated_at=now,
        )
        self.uow.edi_messages.seed(msg)
        res = await self.use_case.execute(
            GetEdiTraceQuery(tenant_id=self.tenant_id, trace_id="trace-ok")
        )
        assert res.is_ok
        result = res.unwrap()
        assert result.edi_message is not None
        assert result.edi_message.trace_id == msg.trace_id
        assert result.edi_message.direction == "INBOUND"

    @pytest.mark.asyncio
    async def test_hydrates_missing_edi_message_from_parent_trace_on_inbound_delivery_retry(
        self,
    ) -> None:
        now = datetime.now(UTC)
        parent_msg = EdiMessage(
            id="msg-parent",
            tenant_id=self.tenant_id,
            trace_id="trace-root",
            connection_type="AS2",
            direction=Direction.INBOUND,
            status=RecordStatus.TRANSFORMED,
            edi_data="ISA*00*...",
            created_at=now,
            updated_at=now,
        )
        child_json = EdiJson(
            id="json-child",
            trace_id="trace-child",
            tenant_id=self.tenant_id,
            direction=Direction.INBOUND,
            status=RecordStatus.DELIVERED,
            parent_trace_id="trace-root",
            original_trace_id="trace-root",
            replay_count=1,
            created_at=now,
            updated_at=now,
        )
        self.uow.edi_messages.seed(parent_msg)
        self.uow.edi_jsons.seed(child_json)

        res = await self.use_case.execute(
            GetEdiTraceQuery(tenant_id=self.tenant_id, trace_id="trace-child")
        )
        assert res.is_ok
        result = res.unwrap()
        assert result.edi_message is not None
        assert result.edi_message.id == "msg-parent"
        assert len(result.edi_jsons) == 1
        assert result.edi_jsons[0].id == "json-child"

    @pytest.mark.asyncio
    async def test_hydrates_missing_edi_jsons_from_parent_trace_on_outbound_delivery_retry(
        self,
    ) -> None:
        now = datetime.now(UTC)
        parent_json = EdiJson(
            id="json-parent",
            trace_id="trace-out-root",
            tenant_id=self.tenant_id,
            direction=Direction.OUTBOUND,
            status=RecordStatus.TRANSFORMED,
            payload={"BEG03": "PO-500"},
            created_at=now,
            updated_at=now,
        )
        child_msg = EdiMessage(
            id="msg-out-child",
            tenant_id=self.tenant_id,
            trace_id="trace-out-child",
            direction=Direction.OUTBOUND,
            status=RecordStatus.DELIVERED,
            parent_trace_id="trace-out-root",
            original_trace_id="trace-out-root",
            replay_count=1,
            created_at=now,
            updated_at=now,
        )
        self.uow.edi_jsons.seed(parent_json)
        self.uow.edi_messages.seed(child_msg)

        res = await self.use_case.execute(
            GetEdiTraceQuery(tenant_id=self.tenant_id, trace_id="trace-out-child")
        )
        assert res.is_ok
        result = res.unwrap()
        assert result.edi_message is not None
        assert result.edi_message.id == "msg-out-child"
        assert len(result.edi_jsons) == 1
        assert result.edi_jsons[0].id == "json-parent"


class TestReplayStageUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo)
        self.use_case = ReplayStageUseCase(
            uow=cast(DataPlaneUnitOfWorkPort, self.uow),
            stage_processors=build_default_edi_stage_replay_processors(),
        )
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_not_found_when_stage_records_missing(self) -> None:
        tx_res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="missing-trace",
                checkpoint=ReplayCheckpoint.TRANSFORM,
                actor="USER",
            )
        )
        assert tx_res.is_err
        assert tx_res.unwrap_err().code == EdiErrorCode.TRACE_NOT_FOUND

        del_res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="missing-trace",
                checkpoint=ReplayCheckpoint.DELIVERY,
                actor="USER",
            )
        )
        assert del_res.is_err
        assert del_res.unwrap_err().code == EdiErrorCode.TRACE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_queues_replay_event_to_transactional_outbox_for_valid_trace(self) -> None:
        model = EdiMessage(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="t-001",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )
        json_model = EdiJson(
            id="json-1",
            tenant_id=self.tenant_id,
            trace_id="t-001",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
            payload={"data": "test"},
        )
        self.uow.edi_messages.seed(model)
        self.uow.edi_jsons.seed(json_model)
        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="t-001",
                checkpoint=ReplayCheckpoint.DELIVERY,
                actor="USER",
            )
        )
        assert res.is_ok
        assert self.uow.committed is True
        assert len(self.uow.outbox_events) == 1
        event = self.uow.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

    @pytest.mark.asyncio
    async def test_replay_event_includes_trace_id_and_unique_idempotency_key(self) -> None:
        model = EdiMessage(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="t-002",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )
        self.uow.edi_messages.seed(model)
        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="t-002",
                checkpoint=ReplayCheckpoint.TRANSFORM,
                actor="USER",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        payload = self.uow.outbox_events[0]["payload"]
        assert isinstance(payload, dict)
        assert payload["trace_id"] == new_trace_id
        assert self.uow.outbox_events[0]["key"] is not None

    @pytest.mark.asyncio
    async def test_inbound_transform_replay_clones_message_only_with_received_status(self) -> None:
        msg = EdiMessage(
            id="msg-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            edi_data="RAW_EDI_DATA",
        )
        json_record = EdiJson(
            id="json-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            payload={"test": "data"},
        )
        self.uow.edi_messages.seed(msg)
        self.uow.edi_jsons.seed(json_record)

        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="trace-in-1",
                checkpoint=ReplayCheckpoint.TRANSFORM,
                actor="USER",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        assert new_trace_id != "trace-in-1"

        cloned_msg = await self.uow.edi_messages.get_edi_message(new_trace_id)
        assert cloned_msg is not None
        assert cloned_msg.status == MessageStatus.RECEIVED
        assert cloned_msg.original_trace_id == "trace-in-1"
        assert cloned_msg.parent_trace_id == "trace-in-1"
        assert cloned_msg.replay_count == 1

        event = self.uow.outbox_events[0]
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

        cloned_json = await self.uow.edi_jsons.get_edi_json(new_trace_id)
        assert cloned_json is None

    @pytest.mark.asyncio
    async def test_inbound_deliver_replay_clones_json_only_with_pending_delivery_status(
        self,
    ) -> None:
        msg = EdiMessage(
            id="msg-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            edi_data="RAW_EDI_DATA",
        )
        json_record = EdiJson(
            id="json-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            payload={"test": "data"},
        )
        self.uow.edi_messages.seed(msg)
        self.uow.edi_jsons.seed(json_record)

        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="trace-in-1",
                checkpoint=ReplayCheckpoint.DELIVERY,
                actor="USER",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        assert new_trace_id != "trace-in-1"

        cloned_json = await self.uow.edi_jsons.get_edi_json(new_trace_id)
        assert cloned_json is not None
        assert cloned_json.status == MessageStatus.PENDING_DELIVERY
        assert cloned_json.original_trace_id == "trace-in-1"
        assert cloned_json.parent_trace_id == "trace-in-1"
        assert cloned_json.replay_count == 1

        event = self.uow.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

        cloned_msg = await self.uow.edi_messages.get_edi_message(new_trace_id)
        assert cloned_msg is None

    @pytest.mark.asyncio
    async def test_outbound_transform_replay_clones_json_only_with_received_status(self) -> None:
        json_record = EdiJson(
            id="json-out-1",
            tenant_id=self.tenant_id,
            trace_id="trace-out-1",
            original_trace_id="trace-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            payload={"order": 123},
        )
        self.uow.edi_jsons.seed(json_record)

        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="trace-out-1",
                checkpoint=ReplayCheckpoint.TRANSFORM,
                actor="USER",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        assert new_trace_id != "trace-out-1"

        cloned_json = await self.uow.edi_jsons.get_edi_json(new_trace_id)
        assert cloned_json is not None
        assert cloned_json.status == MessageStatus.RECEIVED
        assert cloned_json.original_trace_id == "trace-out-1"
        assert cloned_json.parent_trace_id == "trace-out-1"
        assert cloned_json.replay_count == 1

        event = self.uow.outbox_events[0]
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

        cloned_msg = await self.uow.edi_messages.get_edi_message(new_trace_id)
        assert cloned_msg is None

    @pytest.mark.asyncio
    async def test_outbound_deliver_replay_clones_message_only_with_pending_delivery_status(
        self,
    ) -> None:
        json_record = EdiJson(
            id="json-out-1",
            tenant_id=self.tenant_id,
            trace_id="trace-out-1",
            original_trace_id="trace-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.TRANSFORMED,
            payload={"order": 123},
        )
        msg = EdiMessage(
            id="msg-out-1",
            tenant_id=self.tenant_id,
            trace_id="trace-out-1",
            original_trace_id="trace-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            edi_data="ISA*...",
        )
        self.uow.edi_jsons.seed(json_record)
        self.uow.edi_messages.seed(msg)

        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="trace-out-1",
                checkpoint=ReplayCheckpoint.DELIVERY,
                actor="USER",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        assert new_trace_id != "trace-out-1"

        cloned_msg = await self.uow.edi_messages.get_edi_message(new_trace_id)
        assert cloned_msg is not None
        assert cloned_msg.status == MessageStatus.PENDING_DELIVERY
        assert cloned_msg.original_trace_id == "trace-out-1"
        assert cloned_msg.parent_trace_id == "trace-out-1"
        assert cloned_msg.replay_count == 1

        event = self.uow.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

    @pytest.mark.asyncio
    async def test_replay_resolves_parent_stage_when_replaying_from_partial_child_trace(
        self,
    ) -> None:
        root_msg = EdiMessage(
            id="msg-in-root",
            tenant_id=self.tenant_id,
            trace_id="trace-in-root",
            original_trace_id="trace-in-root",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            edi_data="ISA*00*...",
        )
        child_json = EdiJson(
            id="json-in-child",
            tenant_id=self.tenant_id,
            trace_id="trace-in-child",
            parent_trace_id="trace-in-root",
            original_trace_id="trace-in-root",
            replay_count=1,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            payload={"po": "1"},
        )
        self.uow.edi_messages.seed(root_msg)
        self.uow.edi_jsons.seed(child_json)

        res = await self.use_case.execute(
            ReplayStageCommand(
                tenant_id=self.tenant_id,
                trace_id="trace-in-child",
                checkpoint=ReplayCheckpoint.TRANSFORM,
                actor="USER",
            )
        )
        assert res.is_ok
        replayed_trace = res.unwrap()
        cloned_msg = await self.uow.edi_messages.get_edi_message(replayed_trace)
        assert cloned_msg is not None
        assert cloned_msg.original_trace_id == "trace-in-root"


class TestGetEdiTraceLineageUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo)
        self.use_case = GetEdiTraceLineageUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_empty_when_trace_missing(self) -> None:
        assert (
            await self.use_case.execute(
                GetEdiTraceLineageQuery(tenant_id=self.tenant_id, trace_id="nonexistent")
            )
            == []
        )

    @pytest.mark.asyncio
    async def test_lineage_isolation_between_inbound_and_outbound(self) -> None:
        in_msg_1 = EdiMessage(
            id="m-in-1",
            tenant_id=self.tenant_id,
            trace_id="t-in-1",
            original_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            replay_count=0,
        )
        in_msg_2 = EdiMessage(
            id="m-in-2",
            tenant_id=self.tenant_id,
            trace_id="t-in-2",
            original_trace_id="t-in-1",
            parent_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            replay_count=1,
        )
        self.uow.edi_messages.seed(in_msg_1)
        self.uow.edi_messages.seed(in_msg_2)

        out_msg_1 = EdiMessage(
            id="m-out-1",
            tenant_id=self.tenant_id,
            trace_id="t-out-1",
            original_trace_id="t-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            replay_count=0,
        )
        self.uow.edi_messages.seed(out_msg_1)

        lineage = await self.use_case.execute(
            GetEdiTraceLineageQuery(tenant_id=self.tenant_id, trace_id="t-in-1")
        )
        assert len(lineage) == 2
        trace_ids = [item.trace_id for item in lineage]
        assert trace_ids == ["t-in-1", "t-in-2"]
        assert "t-out-1" not in trace_ids

    @pytest.mark.asyncio
    async def test_lineage_includes_downstream_delivery_replay_attempts(self) -> None:
        in_msg_1 = EdiMessage(
            id="m-in-1",
            tenant_id=self.tenant_id,
            trace_id="t-in-1",
            original_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            replay_count=0,
        )
        in_json_1 = EdiJson(
            id="j-in-1",
            tenant_id=self.tenant_id,
            trace_id="t-in-1",
            original_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            replay_count=0,
        )
        self.uow.edi_messages.seed(in_msg_1)
        self.uow.edi_jsons.seed(in_json_1)

        in_json_2 = EdiJson(
            id="j-in-2",
            tenant_id=self.tenant_id,
            trace_id="t-in-2",
            original_trace_id="t-in-1",
            parent_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            replay_count=1,
        )
        self.uow.edi_jsons.seed(in_json_2)

        lineage = await self.use_case.execute(
            GetEdiTraceLineageQuery(tenant_id=self.tenant_id, trace_id="t-in-2")
        )
        assert len(lineage) == 2
        assert lineage[0].trace_id == "t-in-1"
        assert lineage[0].replay_count == 0
        assert lineage[1].trace_id == "t-in-2"
        assert lineage[1].replay_count == 1
        assert lineage[1].status == "DELIVERED"


class TestModifyAndReplayUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo)
        self.use_case = ModifyAndReplayUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_not_found_when_trace_missing(self) -> None:
        res = await self.use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=self.tenant_id,
                original_trace_id="missing-trace",
                modified_payload="ISA*00*...",
                actor="USER",
            )
        )
        assert res.is_err
        assert res.unwrap_err().code == EdiErrorCode.TRACE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_modify_inbound_edi_message_creates_received_clone_and_records_trace_events(
        self,
    ) -> None:
        msg = EdiMessage(
            id="msg-in-1",
            tenant_id=self.tenant_id,
            trace_id="trc-in-orig",
            direction=Direction.INBOUND,
            status=RecordStatus.FAILED,
            edi_data="BAD_EDI",
        )
        self.uow.edi_messages.seed(msg)

        res = await self.use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=self.tenant_id,
                original_trace_id="trc-in-orig",
                modified_payload="FIXED_EDI_PAYLOAD",
                actor="ops@soopa.io",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        created = await self.uow.edi_messages.get_edi_message(new_trace_id)
        assert created is not None
        assert created.edi_data == "FIXED_EDI_PAYLOAD"
        assert created.status == RecordStatus.RECEIVED
        assert created.parent_trace_id == "trc-in-orig"
        assert created.original_trace_id == "trc-in-orig"

        old_events = await self.trace_repo.list_trace_events(self.tenant_id, "trc-in-orig")
        new_events = await self.trace_repo.list_trace_events(self.tenant_id, new_trace_id)
        assert len(old_events) == 1
        assert old_events[0].event_type == EdiTraceEventType.MODIFY_AND_REPLAY_TRANSFORM.value
        assert len(new_events) == 1
        assert new_events[0].event_type == EdiTraceEventType.CREATED_FROM_MODIFICATION.value

    @pytest.mark.asyncio
    async def test_modify_outbound_edi_message_creates_transformed_clone_for_delivery(
        self,
    ) -> None:
        msg = EdiMessage(
            id="msg-out-1",
            tenant_id=self.tenant_id,
            trace_id="trc-out-orig",
            direction=Direction.OUTBOUND,
            status=RecordStatus.FAILED,
            edi_data="OLD_X12",
        )
        self.uow.edi_messages.seed(msg)

        res = await self.use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=self.tenant_id,
                original_trace_id="trc-out-orig",
                modified_payload="NEW_X12",
                actor="ops@soopa.io",
            )
        )
        assert res.is_ok
        new_trace_id = res.unwrap()
        created = await self.uow.edi_messages.get_edi_message(new_trace_id)
        assert created is not None
        assert created.status == RecordStatus.TRANSFORMED
        assert self.uow.outbox_events[-1]["event_type"] == "DELIVERY_REQUESTED"

    @pytest.mark.asyncio
    async def test_modify_outbound_and_inbound_edi_json_and_invalid_json_validation(
        self,
    ) -> None:
        out_json = EdiJson(
            id="json-out-1",
            tenant_id=self.tenant_id,
            trace_id="trc-json-out",
            direction=Direction.OUTBOUND,
            status=RecordStatus.FAILED,
            payload={"BEG03": "OLD"},
        )
        in_json = EdiJson(
            id="json-in-1",
            tenant_id=self.tenant_id,
            trace_id="trc-json-in",
            direction=Direction.INBOUND,
            status=RecordStatus.FAILED,
            payload={"BEG03": "OLD-IN"},
        )
        self.uow.edi_jsons.seed(out_json)
        self.uow.edi_jsons.seed(in_json)

        bad_json_res = await self.use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=self.tenant_id,
                original_trace_id="trc-json-out",
                modified_payload="{invalid-json",
                actor="ops@soopa.io",
            )
        )
        assert bad_json_res.is_err
        assert bad_json_res.unwrap_err().code == EdiErrorCode.INVALID_PAYLOAD

        out_res = await self.use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=self.tenant_id,
                original_trace_id="trc-json-out",
                modified_payload='{"BEG03": "NEW"}',
                actor="ops@soopa.io",
            )
        )
        assert out_res.is_ok
        new_out_trace = out_res.unwrap()
        created_out = await self.uow.edi_jsons.get_edi_json(new_out_trace)
        assert created_out is not None
        assert created_out.status == RecordStatus.RECEIVED
        assert created_out.payload == {"BEG03": "NEW"}

        in_res = await self.use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=self.tenant_id,
                original_trace_id="trc-json-in",
                modified_payload='{"BEG03": "NEW-IN"}',
                actor="ops@soopa.io",
            )
        )
        assert in_res.is_ok
        new_in_trace = in_res.unwrap()
        created_in = await self.uow.edi_jsons.get_edi_json(new_in_trace)
        assert created_in is not None
        assert created_in.status == RecordStatus.TRANSFORMED


@pytest.mark.asyncio
async def test_bulk_replay_transform_and_deliver_commit_and_record_trace_events() -> None:
    trace_repo = InMemoryTraceRepository()
    uow = FakeDataPlaneUnitOfWork(trace_repo)
    tenant_id = generate_id(DomainIdPrefix.TENANT)

    model = EdiMessage(
        id="msg-1",
        tenant_id=tenant_id,
        trace_id="trace-1",
        direction=Direction.INBOUND,
        status=RecordStatus.SUCCESS,
    )
    uow.edi_messages.seed(model)

    use_case = BulkReplayStageUseCase(
        cast(DataPlaneUnitOfWorkPort, uow),
        stage_processors=build_default_edi_stage_replay_processors(),
    )
    tx_res = await use_case.execute(
        BulkReplayStageCommand(
            tenant_id=tenant_id,
            trace_ids=("trace-1",),
            checkpoint=ReplayCheckpoint.TRANSFORM,
            actor="USER",
            command_key="request-1",
        )
    )
    assert tx_res.is_ok
    assert tx_res.unwrap() == 1
    assert uow.committed is True

    del_res = await use_case.execute(
        BulkReplayStageCommand(
            tenant_id=tenant_id,
            trace_ids=("trace-1",),
            checkpoint=ReplayCheckpoint.DELIVERY,
            actor="USER",
            command_key="request-2",
        )
    )
    assert del_res.is_ok
    assert del_res.unwrap() == 1
    recorded_events = await trace_repo.list_trace_events(tenant_id, "trace-1")
    assert [e.event_type for e in recorded_events] == [
        EdiTraceEventType.REPLAY_TRANSFORM.value,
        EdiTraceEventType.REPLAY_DELIVER.value,
    ]

    missing_res = await use_case.execute(
        BulkReplayStageCommand(
            tenant_id=tenant_id,
            trace_ids=("missing-trace",),
            checkpoint=ReplayCheckpoint.TRANSFORM,
            actor="USER",
        )
    )
    assert missing_res.is_err
    assert missing_res.unwrap_err().code == EdiErrorCode.TRACE_NOT_FOUND


class TestListAndExploreEdiStageUseCases:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo)
        self.use_case = ListEdiMessagesUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.json_use_case = ListEdiJsonUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.explore_use_case = ExploreEdiStageUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self) -> None:
        result = await self.use_case.execute(
            ListEdiMessagesQuery(tenant_id=self.tenant_id, limit=10, offset=0)
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_dtos_mapped_from_domain_models_for_messages_json_and_explorer(
        self,
    ) -> None:
        now = datetime.now(UTC)
        self.uow.edi_messages.seed(
            EdiMessage(
                id="msg-1",
                tenant_id=self.tenant_id,
                trace_id="t-001",
                sender_id="SENDER_A",
                connection_type="AS2",
                direction=Direction.INBOUND,
                status=RecordStatus.SUCCESS,
                created_at=now,
                updated_at=now,
            )
        )
        self.uow.edi_messages.seed(
            EdiMessage(
                id="msg-2",
                tenant_id=self.tenant_id,
                trace_id="t-002",
                sender_id="SENDER_B",
                connection_type="AS2",
                direction=Direction.INBOUND,
                status=RecordStatus.SUCCESS,
                created_at=now,
                updated_at=now,
            )
        )
        result = await self.use_case.execute(
            ListEdiMessagesQuery(tenant_id=self.tenant_id, limit=1, offset=1)
        )
        assert len(result) == 1
        assert result[0].trace_id == "t-002"

        self.uow.edi_jsons.seed(
            EdiJson(
                id="json-thread-1",
                tenant_id=self.tenant_id,
                trace_id="t-001",
                direction=Direction.INBOUND,
                status=RecordStatus.SUCCESS,
                business_metadata={"po_number": "PO-999"},
                payload={"po": "PO-999"},
                created_at=now,
                updated_at=now,
            )
        )
        thread = await self.json_use_case.execute(
            ListEdiJsonQuery(tenant_id=self.tenant_id, key="po_number", value="PO-999")
        )
        assert len(thread) == 1
        assert thread[0].trace_id == "t-001"

        explore_res = await self.explore_use_case.explore_messages(
            ExploreEdiMessagesQuery(
                tenant_id=self.tenant_id,
                filters=(RawStageFilterInput(field="sender_id", operator="eq", value="SENDER_A"),),
            )
        )
        assert explore_res.is_ok
        assert [m.trace_id for m in explore_res.unwrap()] == ["t-001"]

        unsupported_json_filter = await self.explore_use_case.explore_json(
            ExploreEdiJsonQuery(
                tenant_id=self.tenant_id,
                filters=(RawStageFilterInput(field="sender_id", operator="eq", value="SENDER_A"),),
            )
        )
        assert unsupported_json_filter.is_err
        assert unsupported_json_filter.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED
