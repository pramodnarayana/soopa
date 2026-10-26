"""Application use-case unit tests for EDI Transactions, Trace Waterfall, Lineage, and Replay."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest
from seedwork.domain.types import JsonValue
from seedwork.events import EventEnvelope
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from strace.domain import TraceEventType
from strace.testing import InMemoryTraceRepository

from edi.application.dtos.trace import EdiTraceDTO
from edi.application.dtos.transactions import ApiGatewayDTO, EdiJsonDTO, EdiMessageDTO
from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_lineage_use_case import (
    GetEdiTraceLineageUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_use_case import (
    GetEdiTraceUseCase,
)
from edi.application.use_cases.transactions.list_edi_json_use_case import (
    ListEdiJsonUseCase,
)
from edi.application.use_cases.transactions.list_edi_messages_use_case import (
    ListEdiMessagesUseCase,
)
from edi.application.use_cases.transactions.modify_and_replay_use_case import (
    ModifyAndReplayTransactionUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from edi.domain.enums import EdiDirection, MessageStatus, TransactionEntityType
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from edi.testing.fakes.pipeline_fakes import FakeOutboxPublisher


@dataclass
class FakeRoutingContextResolver:
    tenant_id: str
    channel: str
    resolved: bool = False

    async def resolve_routing_context(
        self,
        edi_message: EdiMessageDTO | None,
        edi_jsons: Sequence[EdiJsonDTO],
    ) -> tuple[str, str]:
        _ = (edi_message, edi_jsons)
        self.resolved = True
        return self.tenant_id, self.channel


class FakeEdiMessageRepository:
    def __init__(self) -> None:
        self._messages: list[EdiMessageDTO] = []
        self._message_dtos: dict[str, EdiMessageDTO] = {}
        self._json_dtos: dict[str, list[EdiJsonDTO]] = {}
        self._api_gateway_dtos: dict[str, list[ApiGatewayDTO]] = {}
        self._models: dict[str, EdiMessageDomainModel] = {}
        self._json_models: dict[str, EdiJsonDomainModel] = {}
        self.outbox_events: list[dict[str, object]] = []

    def seed_trace_dtos(self, tenant_id: str, trace_id: str, result: EdiTraceDTO) -> None:
        key = f"{tenant_id}:{trace_id}"
        if result.edi_message is not None:
            self._message_dtos[key] = result.edi_message
        self._json_dtos[key] = list(result.edi_jsons)
        self._api_gateway_dtos[key] = list(result.api_gateways)

    async def get_edi_message_dto(self, tenant_id: str, trace_id: str) -> EdiMessageDTO | None:
        return self._message_dtos.get(f"{tenant_id}:{trace_id}")

    async def get_edi_json_dtos_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[EdiJsonDTO]:
        return list(self._json_dtos.get(f"{tenant_id}:{trace_id}", []))

    async def get_api_gateways_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[ApiGatewayDTO]:
        return list(self._api_gateway_dtos.get(f"{tenant_id}:{trace_id}", []))

    def seed_summaries(self, summaries: list[EdiMessageDTO]) -> None:
        self._messages = summaries

    def seed_model(self, model: EdiMessageDomainModel) -> None:
        self._models[model.id] = model

    def seed_json_model(self, model: EdiJsonDomainModel) -> None:
        self._json_models[model.id] = model

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> list[EdiMessageDTO]:
        _ = (tenant_id, partner_id, transaction_type, direction)
        return self._messages[offset : offset + limit]

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> list[EdiJsonDTO]:
        results: list[EdiJsonDTO] = []
        for j in self._json_models.values():
            if (
                j.tenant_id == tenant_id
                and j.business_metadata
                and j.business_metadata.get(key) == value
            ):
                results.append(
                    EdiJsonDTO(
                        id=j.id,
                        trace_id=j.trace_id,
                        tenant_id=j.tenant_id,
                        direction=j.direction.value if j.direction else "INBOUND",
                        status=j.status.value if j.status else "UNKNOWN",
                        payload=j.payload,
                        business_metadata=j.business_metadata,
                        created_at=j.created_at,
                        updated_at=j.updated_at,
                    )
                )
        return results

    async def explorer_list_edi_messages(
        self,
        tenant_id: str,
        filters: list[dict[str, JsonValue]],
        limit: int = 50,
        offset: int = 0,
    ) -> list[EdiMessageDTO]:
        _ = (limit, offset)
        results = []
        for m in self._models.values():
            if m.tenant_id != tenant_id:
                continue
            matches = True
            for f in filters:
                field = f.get("field")
                val = f.get("value")
                if (
                    field == "original_trace_id"
                    and (m.original_trace_id != val and m.trace_id != val)
                ) or (field == "direction" and (m.direction.value if m.direction else None) != val):
                    matches = False
            if matches:
                results.append(
                    EdiMessageDTO(
                        id=m.id,
                        trace_id=m.trace_id,
                        direction=m.direction.value if m.direction else "INBOUND",
                        status=m.status.value if m.status else "UNKNOWN",
                        created_at=m.created_at,
                        updated_at=m.updated_at,
                        replay_count=m.replay_count,
                        parent_trace_id=m.parent_trace_id,
                        original_trace_id=m.original_trace_id,
                    )
                )
        return results

    async def explorer_list_edi_json(
        self,
        tenant_id: str,
        filters: list[dict[str, JsonValue]],
        limit: int = 50,
        offset: int = 0,
    ) -> list[EdiJsonDTO]:
        _ = (limit, offset)
        results = []
        for j in self._json_models.values():
            if j.tenant_id != tenant_id:
                continue
            matches = True
            for f in filters:
                field = f.get("field")
                val = f.get("value")
                if (
                    field == "original_trace_id"
                    and (j.original_trace_id != val and j.trace_id != val)
                ) or (field == "direction" and (j.direction.value if j.direction else None) != val):
                    matches = False
            if matches:
                results.append(
                    EdiJsonDTO(
                        id=j.id,
                        trace_id=j.trace_id,
                        tenant_id=j.tenant_id,
                        direction=j.direction.value if j.direction else "INBOUND",
                        status=j.status.value if j.status else "UNKNOWN",
                        payload=j.payload,
                        created_at=j.created_at,
                        updated_at=j.updated_at,
                        replay_count=j.replay_count,
                        parent_trace_id=j.parent_trace_id,
                        original_trace_id=j.original_trace_id,
                    )
                )
        return results

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessageDomainModel | None:
        for model in self._models.values():
            if model.trace_id == trace_id and (tenant_id is None or model.tenant_id == tenant_id):
                return model
        return None

    async def get_edi_json(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiJsonDomainModel | None:
        for model in self._json_models.values():
            if model.trace_id == trace_id and (tenant_id is None or model.tenant_id == tenant_id):
                return model
        return None

    async def get_edi_jsons_by_trace_id(
        self, trace_id: str, tenant_id: str | None = None
    ) -> list[EdiJsonDomainModel]:
        return [
            model
            for model in self._json_models.values()
            if model.trace_id == trace_id and (tenant_id is None or model.tenant_id == tenant_id)
        ]

    async def save_message(self, record: EdiMessageDomainModel) -> None:
        self._models[record.id] = record

    async def save_json(self, record: EdiJsonDomainModel) -> list[EventEnvelope]:
        self._json_models[record.id] = record
        return await self._drain_domain_events(record)

    async def save(self, model: EdiMessageDomainModel) -> list[EventEnvelope]:
        self._models[model.id] = model
        return await self._drain_domain_events(model)

    async def _drain_domain_events(
        self, model: EdiMessageDomainModel | EdiJsonDomainModel
    ) -> list[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        for e in model.domain_events:
            event_type = e.event_name
            payload = dataclasses.asdict(e)
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
            self.outbox_events.append(
                {
                    "tenant_id": model.tenant_id,
                    "event_type": event_type,
                    "payload": payload,
                    "key": key,
                }
            )
        model.clear_domain_events()
        return envelopes

    async def save_all(self, models: Sequence[EdiMessageDomainModel]) -> list[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        for model in models:
            envelopes.extend(await self.save(model))
        return envelopes

    async def get_edi_messages_by_traces(
        self, tenant_id: str, trace_ids: Sequence[str]
    ) -> list[EdiMessageDomainModel]:
        found = [
            m for m in self._models.values() if m.tenant_id == tenant_id and m.trace_id in trace_ids
        ]
        return found

    async def increment_replay_count(
        self,
        tenant_id: str,
        trace_ids: Sequence[str],
        entity_types: Sequence[TransactionEntityType],
    ) -> None:
        _ = (tenant_id, entity_types)
        for trace_id in trace_ids:
            for model in self._models.values():
                if model.trace_id == trace_id:
                    model.replay_count += 1


class FakeOutboxRepo:
    def __init__(self) -> None:
        self.completed_ids: list[str] = []

    async def mark_completed(self, event_id: str) -> None:
        self.completed_ids.append(event_id)


class FakeDataPlaneUnitOfWork:
    def __init__(
        self,
        trace_repo: InMemoryTraceRepository,
        message_repo: FakeEdiMessageRepository,
    ) -> None:
        self.traces = trace_repo
        self.edi_messages = message_repo
        self.transactions = message_repo
        self.api_gateway_transactions = message_repo
        self.outbox = FakeOutboxRepo()
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
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = GetEdiTraceUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_trace_missing(self) -> None:
        with pytest.raises(TransactionNotFoundError) as exc_info:
            await self.use_case.get_edi_trace(self.tenant_id, "missing-trace")
        assert exc_info.value.trace_id == "missing-trace"

    @pytest.mark.asyncio
    async def test_returns_trace_result(self) -> None:
        msg = EdiMessageDTO(
            id="msg-1",
            trace_id="trace-ok",
            connection_type="AS2",
            direction="INBOUND",
            status="SUCCESS",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.msg_repo.seed_trace_dtos(
            self.tenant_id,
            "trace-ok",
            EdiTraceDTO(edi_message=msg, edi_jsons=[], api_gateways=[]),
        )
        result = await self.use_case.get_edi_trace(self.tenant_id, "trace-ok")
        assert result.edi_message is not None
        assert result.edi_message.trace_id == msg.trace_id
        assert result.edi_message.direction == "INBOUND"

    @pytest.mark.asyncio
    async def test_hydrates_missing_edi_message_from_parent_trace_on_inbound_delivery_retry(
        self,
    ) -> None:
        now = datetime.now(UTC)
        parent_msg = EdiMessageDTO(
            id="msg-parent",
            trace_id="trace-root",
            connection_type="AS2",
            direction="INBOUND",
            status="TRANSFORMED",
            edi_data="ISA*00*...",
            created_at=now,
            updated_at=now,
        )
        child_json = EdiJsonDTO(
            id="json-child",
            trace_id="trace-child",
            tenant_id=self.tenant_id,
            direction="INBOUND",
            status="DELIVERED",
            parent_trace_id="trace-root",
            original_trace_id="trace-root",
            replay_count=1,
            created_at=now,
            updated_at=now,
        )
        self.msg_repo.seed_trace_dtos(
            self.tenant_id,
            "trace-root",
            EdiTraceDTO(edi_message=parent_msg, edi_jsons=[], api_gateways=[]),
        )
        self.msg_repo.seed_trace_dtos(
            self.tenant_id,
            "trace-child",
            EdiTraceDTO(edi_message=None, edi_jsons=[child_json], api_gateways=[]),
        )

        result = await self.use_case.get_edi_trace(self.tenant_id, "trace-child")
        assert result.edi_message is not None
        assert result.edi_message.id == "msg-parent"
        assert len(result.edi_jsons) == 1
        assert result.edi_jsons[0].id == "json-child"

    @pytest.mark.asyncio
    async def test_hydrates_missing_edi_jsons_from_parent_trace_on_outbound_delivery_retry(
        self,
    ) -> None:
        now = datetime.now(UTC)
        parent_json = EdiJsonDTO(
            id="json-parent",
            trace_id="trace-out-root",
            tenant_id=self.tenant_id,
            direction="OUTBOUND",
            status="TRANSFORMED",
            payload={"BEG03": "PO-500"},
            created_at=now,
            updated_at=now,
        )
        child_msg = EdiMessageDTO(
            id="msg-out-child",
            trace_id="trace-out-child",
            direction="OUTBOUND",
            status="DELIVERED",
            parent_trace_id="trace-out-root",
            original_trace_id="trace-out-root",
            replay_count=1,
            created_at=now,
            updated_at=now,
        )
        self.msg_repo.seed_trace_dtos(
            self.tenant_id,
            "trace-out-root",
            EdiTraceDTO(edi_message=None, edi_jsons=[parent_json], api_gateways=[]),
        )
        self.msg_repo.seed_trace_dtos(
            self.tenant_id,
            "trace-out-child",
            EdiTraceDTO(edi_message=child_msg, edi_jsons=[], api_gateways=[]),
        )

        result = await self.use_case.get_edi_trace(self.tenant_id, "trace-out-child")
        assert result.edi_message is not None
        assert result.edi_message.id == "msg-out-child"
        assert len(result.edi_jsons) == 1
        assert result.edi_jsons[0].id == "json-parent"


class TestReplayTransactionUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.publisher = FakeOutboxPublisher()
        self.use_case = ReplayTransactionUseCase(
            uow=cast(DataPlaneUnitOfWorkPort, self.uow),
            publisher=self.publisher,
        )
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_transaction_missing(self) -> None:
        with pytest.raises(TransactionNotFoundError) as exc_info:
            await self.use_case.retry_transform(self.tenant_id, "missing-trace", actor="USER")
        assert exc_info.value.trace_id == "missing-trace"

        with pytest.raises(TransactionNotFoundError):
            await self.use_case.retry_deliver(self.tenant_id, "missing-trace", actor="USER")

    @pytest.mark.asyncio
    async def test_publishes_replay_event_for_valid_trace(self) -> None:
        model = EdiMessageDomainModel(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="t-001",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )
        json_model = EdiJsonDomainModel(
            id="json-1",
            tenant_id=self.tenant_id,
            trace_id="t-001",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
            payload={"data": "test"},
        )
        self.msg_repo.seed_model(model)
        self.msg_repo.seed_json_model(json_model)
        await self.use_case.retry_deliver(self.tenant_id, "t-001", actor="USER")
        assert len(self.msg_repo.outbox_events) == 1
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"
        assert len(self.publisher.published_events) == 1

    @pytest.mark.asyncio
    async def test_replay_event_includes_trace_id_and_unique_idempotency_key(self) -> None:
        model = EdiMessageDomainModel(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="t-002",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )
        self.msg_repo.seed_model(model)
        new_trace_id = await self.use_case.retry_transform(self.tenant_id, "t-002", actor="USER")
        payload = self.msg_repo.outbox_events[0]["payload"]
        assert isinstance(payload, dict)
        assert payload["trace_id"] == new_trace_id
        assert self.msg_repo.outbox_events[0]["key"] is not None

    @pytest.mark.asyncio
    async def test_inbound_transform_replay_clones_message_only_with_received_status(self) -> None:
        msg = EdiMessageDomainModel(
            id="msg-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            edi_data="RAW_EDI_DATA",
        )
        json_record = EdiJsonDomainModel(
            id="json-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            payload={"test": "data"},
        )
        self.msg_repo.seed_model(msg)
        self.msg_repo.seed_json_model(json_record)

        new_trace_id = await self.use_case.retry_transform(
            self.tenant_id, "trace-in-1", actor="USER"
        )
        assert new_trace_id != "trace-in-1"

        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is not None
        assert cloned_msg.status == MessageStatus.RECEIVED
        assert cloned_msg.original_trace_id == "trace-in-1"
        assert cloned_msg.parent_trace_id == "trace-in-1"
        assert cloned_msg.replay_count == 1

        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

        cloned_json = await self.msg_repo.get_edi_json(new_trace_id)
        assert cloned_json is None

    @pytest.mark.asyncio
    async def test_inbound_deliver_replay_clones_json_only_with_pending_delivery_status(
        self,
    ) -> None:
        msg = EdiMessageDomainModel(
            id="msg-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            edi_data="RAW_EDI_DATA",
        )
        json_record = EdiJsonDomainModel(
            id="json-in-1",
            tenant_id=self.tenant_id,
            trace_id="trace-in-1",
            original_trace_id="trace-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            payload={"test": "data"},
        )
        self.msg_repo.seed_model(msg)
        self.msg_repo.seed_json_model(json_record)

        new_trace_id = await self.use_case.retry_deliver(self.tenant_id, "trace-in-1", actor="USER")
        assert new_trace_id != "trace-in-1"

        cloned_json = await self.msg_repo.get_edi_json(new_trace_id)
        assert cloned_json is not None
        assert cloned_json.status == MessageStatus.PENDING_DELIVERY
        assert cloned_json.original_trace_id == "trace-in-1"
        assert cloned_json.parent_trace_id == "trace-in-1"
        assert cloned_json.replay_count == 1

        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is None

    @pytest.mark.asyncio
    async def test_outbound_transform_replay_clones_json_only_with_received_status(self) -> None:
        json_record = EdiJsonDomainModel(
            id="json-out-1",
            tenant_id=self.tenant_id,
            trace_id="trace-out-1",
            original_trace_id="trace-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            payload={"order": 123},
        )
        self.msg_repo.seed_json_model(json_record)

        new_trace_id = await self.use_case.retry_transform(
            self.tenant_id, "trace-out-1", actor="USER"
        )
        assert new_trace_id != "trace-out-1"

        cloned_json = await self.msg_repo.get_edi_json(new_trace_id)
        assert cloned_json is not None
        assert cloned_json.status == MessageStatus.RECEIVED
        assert cloned_json.original_trace_id == "trace-out-1"
        assert cloned_json.parent_trace_id == "trace-out-1"
        assert cloned_json.replay_count == 1

        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is None

    @pytest.mark.asyncio
    async def test_outbound_deliver_replay_clones_message_only_with_pending_delivery_status(
        self,
    ) -> None:
        json_record = EdiJsonDomainModel(
            id="json-out-1",
            tenant_id=self.tenant_id,
            trace_id="trace-out-1",
            original_trace_id="trace-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.TRANSFORMED,
            payload={"order": 123},
        )
        msg = EdiMessageDomainModel(
            id="msg-out-1",
            tenant_id=self.tenant_id,
            trace_id="trace-out-1",
            original_trace_id="trace-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            edi_data="ISA*...",
        )
        self.msg_repo.seed_json_model(json_record)
        self.msg_repo.seed_model(msg)

        new_trace_id = await self.use_case.retry_deliver(
            self.tenant_id, "trace-out-1", actor="USER"
        )
        assert new_trace_id != "trace-out-1"

        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is not None
        assert cloned_msg.status == MessageStatus.PENDING_DELIVERY
        assert cloned_msg.original_trace_id == "trace-out-1"
        assert cloned_msg.parent_trace_id == "trace-out-1"
        assert cloned_msg.replay_count == 1

        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

    @pytest.mark.asyncio
    async def test_replay_resolves_parent_stage_when_replaying_from_partial_child_trace(
        self,
    ) -> None:
        # Inbound root has EdiMessage; child delivery retry only has EdiJson.
        # Calling retry_transform on child_trace_id must walk parent_trace_id to clone EdiMessage!
        root_msg = EdiMessageDomainModel(
            id="msg-in-root",
            tenant_id=self.tenant_id,
            trace_id="trace-in-root",
            original_trace_id="trace-in-root",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            edi_data="ISA*00*...",
        )
        child_json = EdiJsonDomainModel(
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
        self.msg_repo.seed_model(root_msg)
        self.msg_repo.seed_json_model(child_json)

        replayed_trace = await self.use_case.retry_transform(
            self.tenant_id, "trace-in-child", actor="USER"
        )
        cloned_msg = await self.msg_repo.get_edi_message(replayed_trace)
        assert cloned_msg is not None
        assert cloned_msg.original_trace_id == "trace-in-root"


class TestGetEdiTraceLineageUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = GetEdiTraceLineageUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_empty_when_trace_missing(self) -> None:
        assert await self.use_case.execute(self.tenant_id, "nonexistent") == []

    @pytest.mark.asyncio
    async def test_lineage_isolation_between_inbound_and_outbound(self) -> None:
        in_msg_1 = EdiMessageDomainModel(
            id="m-in-1",
            tenant_id=self.tenant_id,
            trace_id="t-in-1",
            original_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            replay_count=0,
        )
        in_msg_2 = EdiMessageDomainModel(
            id="m-in-2",
            tenant_id=self.tenant_id,
            trace_id="t-in-2",
            original_trace_id="t-in-1",
            parent_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            replay_count=1,
        )
        self.msg_repo.seed_model(in_msg_1)
        self.msg_repo.seed_model(in_msg_2)

        out_msg_1 = EdiMessageDomainModel(
            id="m-out-1",
            tenant_id=self.tenant_id,
            trace_id="t-out-1",
            original_trace_id="t-out-1",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            replay_count=0,
        )
        self.msg_repo.seed_model(out_msg_1)

        lineage = await self.use_case.execute(self.tenant_id, "t-in-1")
        assert len(lineage) == 2
        trace_ids = [item.trace_id for item in lineage]
        assert trace_ids == ["t-in-1", "t-in-2"]
        assert "t-out-1" not in trace_ids

    @pytest.mark.asyncio
    async def test_lineage_includes_downstream_delivery_replay_attempts(self) -> None:
        in_msg_1 = EdiMessageDomainModel(
            id="m-in-1",
            tenant_id=self.tenant_id,
            trace_id="t-in-1",
            original_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            replay_count=0,
        )
        in_json_1 = EdiJsonDomainModel(
            id="j-in-1",
            tenant_id=self.tenant_id,
            trace_id="t-in-1",
            original_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            replay_count=0,
        )
        self.msg_repo.seed_model(in_msg_1)
        self.msg_repo.seed_json_model(in_json_1)

        in_json_2 = EdiJsonDomainModel(
            id="j-in-2",
            tenant_id=self.tenant_id,
            trace_id="t-in-2",
            original_trace_id="t-in-1",
            parent_trace_id="t-in-1",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            replay_count=1,
        )
        self.msg_repo.seed_json_model(in_json_2)

        lineage = await self.use_case.execute(self.tenant_id, "t-in-2")
        assert len(lineage) == 2
        assert lineage[0].trace_id == "t-in-1"
        assert lineage[0].replay_count == 0
        assert lineage[1].trace_id == "t-in-2"
        assert lineage[1].replay_count == 1
        assert lineage[1].status == "DELIVERED"


class TestModifyAndReplayTransactionUseCase:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.publisher = FakeOutboxPublisher()
        self.use_case = ModifyAndReplayTransactionUseCase(
            uow=cast(DataPlaneUnitOfWorkPort, self.uow),
            publisher=self.publisher,
        )
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_trace_missing(self) -> None:
        with pytest.raises(TransactionNotFoundError):
            await self.use_case.execute(self.tenant_id, "missing-trace", "ISA*00*...", actor="USER")

    @pytest.mark.asyncio
    async def test_modify_inbound_edi_message_creates_received_clone_and_records_trace_events(
        self,
    ) -> None:
        msg = EdiMessageDomainModel(
            id="msg-in-1",
            tenant_id=self.tenant_id,
            trace_id="trc-in-orig",
            direction=Direction.INBOUND,
            status=RecordStatus.FAILED,
            edi_data="BAD_EDI",
        )
        self.msg_repo.seed_model(msg)

        new_trace_id = await self.use_case.execute(
            self.tenant_id, "trc-in-orig", "FIXED_EDI_PAYLOAD", actor="ops@soopa.io"
        )
        created = await self.msg_repo.get_edi_message(new_trace_id)
        assert created is not None
        assert created.edi_data == "FIXED_EDI_PAYLOAD"
        assert created.status == RecordStatus.RECEIVED
        assert created.parent_trace_id == "trc-in-orig"
        assert created.original_trace_id == "trc-in-orig"

        old_events = await self.trace_repo.list_trace_events(self.tenant_id, "trc-in-orig")
        new_events = await self.trace_repo.list_trace_events(self.tenant_id, new_trace_id)
        assert len(old_events) == 1
        assert old_events[0].event_type == TraceEventType.MODIFY_AND_REPLAY_TRANSFORM.value
        assert len(new_events) == 1
        assert new_events[0].event_type == TraceEventType.CREATED_FROM_MODIFICATION.value

    @pytest.mark.asyncio
    async def test_modify_outbound_edi_message_creates_transformed_clone_for_delivery(
        self,
    ) -> None:
        msg = EdiMessageDomainModel(
            id="msg-out-1",
            tenant_id=self.tenant_id,
            trace_id="trc-out-orig",
            direction=Direction.OUTBOUND,
            status=RecordStatus.FAILED,
            edi_data="OLD_X12",
        )
        self.msg_repo.seed_model(msg)

        new_trace_id = await self.use_case.execute(
            self.tenant_id, "trc-out-orig", "NEW_X12", actor="ops@soopa.io"
        )
        created = await self.msg_repo.get_edi_message(new_trace_id)
        assert created is not None
        assert created.status == RecordStatus.TRANSFORMED
        assert self.msg_repo.outbox_events[-1]["event_type"] == "DELIVERY_REQUESTED"

    @pytest.mark.asyncio
    async def test_modify_outbound_and_inbound_edi_json_and_invalid_json_validation(
        self,
    ) -> None:
        out_json = EdiJsonDomainModel(
            id="json-out-1",
            tenant_id=self.tenant_id,
            trace_id="trc-json-out",
            direction=Direction.OUTBOUND,
            status=RecordStatus.FAILED,
            payload={"BEG03": "OLD"},
        )
        in_json = EdiJsonDomainModel(
            id="json-in-1",
            tenant_id=self.tenant_id,
            trace_id="trc-json-in",
            direction=Direction.INBOUND,
            status=RecordStatus.FAILED,
            payload={"BEG03": "OLD-IN"},
        )
        self.msg_repo.seed_json_model(out_json)
        self.msg_repo.seed_json_model(in_json)

        with pytest.raises(ValueError, match="Invalid JSON payload"):
            await self.use_case.execute(
                self.tenant_id, "trc-json-out", "{invalid-json", actor="ops@soopa.io"
            )

        new_out_trace = await self.use_case.execute(
            self.tenant_id, "trc-json-out", '{"BEG03": "NEW"}', actor="ops@soopa.io"
        )
        created_out = await self.msg_repo.get_edi_json(new_out_trace)
        assert created_out is not None
        assert created_out.status == RecordStatus.RECEIVED
        assert created_out.payload == {"BEG03": "NEW"}

        new_in_trace = await self.use_case.execute(
            self.tenant_id, "trc-json-in", '{"BEG03": "NEW-IN"}', actor="ops@soopa.io"
        )
        created_in = await self.msg_repo.get_edi_json(new_in_trace)
        assert created_in is not None
        assert created_in.status == RecordStatus.TRANSFORMED


@pytest.mark.asyncio
async def test_bulk_replay_transform_and_deliver_commit_and_record_trace_events() -> None:
    trace_repo = InMemoryTraceRepository()
    msg_repo = FakeEdiMessageRepository()
    uow = FakeDataPlaneUnitOfWork(trace_repo, msg_repo)
    tenant_id = generate_id(DomainIdPrefix.TENANT)

    model = EdiMessageDomainModel(
        id="msg-1",
        tenant_id=tenant_id,
        trace_id="trace-1",
        direction=Direction.INBOUND,
        status=RecordStatus.SUCCESS,
    )
    msg_repo.seed_model(model)

    use_case = BulkReplayTransactionsUseCase(
        cast(DataPlaneUnitOfWorkPort, uow),
        publisher=FakeOutboxPublisher(),
    )
    count = await use_case.bulk_retry_transform(
        tenant_id, ["trace-1"], "USER", command_key="request-1"
    )
    assert count == 1
    assert uow.committed is True

    deliver_count = await use_case.bulk_retry_deliver(
        tenant_id, ["trace-1"], "USER", command_key="request-2"
    )
    assert deliver_count == 1
    recorded_events = await trace_repo.list_trace_events(tenant_id, "trace-1")
    assert [e.event_type for e in recorded_events] == [
        TraceEventType.REPLAY_TRANSFORM.value,
        TraceEventType.REPLAY_DELIVER.value,
    ]

    with pytest.raises(TransactionNotFoundError):
        await use_case.bulk_retry_transform(tenant_id, ["missing-trace"], "USER")


class TestListEdiMessagesAndJsonUseCases:
    def setup_method(self) -> None:
        self.trace_repo = InMemoryTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = ListEdiMessagesUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.json_use_case = ListEdiJsonUseCase(uow=cast(DataPlaneUnitOfWorkPort, self.uow))
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self) -> None:
        result = await self.use_case.list_edi_messages(self.tenant_id, limit=10, offset=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_domain_models_for_found_messages_and_json_threads(self) -> None:
        self.msg_repo.seed_summaries(
            [
                EdiMessageDTO(
                    id="msg-1",
                    trace_id="t-001",
                    connection_type="AS2",
                    direction="INBOUND",
                    status="SUCCESS",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                EdiMessageDTO(
                    id="msg-2",
                    trace_id="t-002",
                    connection_type="AS2",
                    direction="INBOUND",
                    status="SUCCESS",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        result = await self.use_case.list_edi_messages(self.tenant_id, limit=1, offset=1)
        assert len(result) == 1
        assert result[0].trace_id == "t-002"

        self.msg_repo.seed_json_model(
            EdiJsonDomainModel(
                id="json-thread-1",
                tenant_id=self.tenant_id,
                trace_id="t-001",
                direction=Direction.INBOUND,
                status=RecordStatus.SUCCESS,
                business_metadata={"po_number": "PO-999"},
                payload={"po": "PO-999"},
            )
        )
        thread = await self.json_use_case.list_edi_json(self.tenant_id, "po_number", "PO-999")
        assert len(thread) == 1
        assert thread[0].trace_id == "t-001"
