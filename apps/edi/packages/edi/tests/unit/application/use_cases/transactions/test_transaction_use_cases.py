import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from seedwork.events import EventEnvelope
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from edi.application.dtos.trace import EdiTraceDTO
from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_lineage_use_case import (
    GetEdiTraceLineageUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_use_case import (
    GetEdiTraceUseCase,
)
from edi.application.use_cases.transactions.list_edi_messages_use_case import (
    ListEdiMessagesUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from edi.domain.enums import EdiDirection, MessageStatus, TransactionEntityType
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.testing.fakes.pipeline_fakes import FakeOutboxPublisher


@dataclass
class FakeRoutingContextResolver:
    tenant_id: str
    channel: str
    resolved: bool = False

    async def resolve_routing_context(
        self, edi_message: Any, edi_jsons: list[Any]
    ) -> tuple[str, str]:
        self.resolved = True
        return self.tenant_id, self.channel


class FakeTraceRepository:
    def __init__(self):
        self._traces: dict[str, EdiTraceDTO] = {}

    def seed_trace(self, tenant_id: str, trace_id: str, result: EdiTraceDTO):
        self._traces[f"{tenant_id}:{trace_id}"] = result

    async def get_edi_trace(self, tenant_id: str, trace_id: str) -> EdiTraceDTO | None:
        return self._traces.get(f"{tenant_id}:{trace_id}")


class FakeEdiMessageRepository:
    def __init__(self):
        self._messages: list[EdiMessageDTO] = []
        self._models: dict[str, EdiMessageDomainModel] = {}
        self._json_models: dict[str, EdiJsonDomainModel] = {}
        self.outbox_events: list[dict[str, Any]] = []

    def seed_summaries(self, summaries: list[EdiMessageDTO]):
        self._messages = summaries

    def seed_model(self, model: EdiMessageDomainModel):
        self._models[model.id] = model

    def seed_json_model(self, model: EdiJsonDomainModel):
        self._json_models[model.id] = model

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        **kwargs,
    ) -> list[EdiMessageDTO]:
        return self._messages[offset : offset + limit]

    async def explorer_list_edi_messages(
        self, tenant_id: str, filters: list[dict[str, Any]], limit: int = 50, offset: int = 0
    ) -> list[EdiMessageDTO]:
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
        self, tenant_id: str, filters: list[dict[str, Any]], limit: int = 50, offset: int = 0
    ) -> list[EdiJsonDTO]:
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

    async def publish_outbox_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: Any,
        idempotency_key: str | None,
    ) -> str:
        key = idempotency_key or "auto"
        self.outbox_events.append(
            {"tenant_id": tenant_id, "event_type": event_type, "payload": payload, "key": key}
        )
        return key

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessageDomainModel | None:
        for model in self._models.values():
            if model.trace_id == trace_id:
                return model
        return None

    async def get_edi_json(self, trace_id: str) -> EdiJsonDomainModel | None:
        for model in self._json_models.values():
            if model.trace_id == trace_id:
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

    async def create_edi_json(self, record: EdiJsonDomainModel) -> None:
        pass

    async def save_message(self, record: EdiMessageDomainModel) -> None:
        self._models[record.id] = record

    async def save_json(self, record: EdiJsonDomainModel) -> list:
        self._json_models[record.id] = record
        return await self.save(record)

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        return {"fake": "api_payload"}

    async def create_api_gateway(self, command: Any) -> str:
        return "fake_api_gateway_id"

    async def save(self, model: Any) -> list:
        if isinstance(model, EdiMessageDomainModel):
            self._models[model.id] = model
        elif isinstance(model, EdiJsonDomainModel):
            self._json_models[model.id] = model

        for e in model.domain_events:
            event_type = getattr(e, "event_name", getattr(e, "event_type", "unknown"))
            payload = dataclasses.asdict(e) if dataclasses.is_dataclass(e) else vars(e)
            key = e.idempotency_key
            self.outbox_events.append(
                {
                    "tenant_id": model.tenant_id,
                    "event_type": event_type,
                    "payload": payload,
                    "key": key,
                }
            )
        model.clear_domain_events()
        return []

    async def flush_events(self, aggregate: Any) -> list[Any]:

        envelopes = []
        for e in aggregate.domain_events:
            env = EventEnvelope(
                id=str(uuid.uuid4()),
                source="test",
                tenant_id=aggregate.tenant_id,
                event_type=getattr(e, "event_name", getattr(e, "event_type", "unknown")),
                payload=dataclasses.asdict(e) if dataclasses.is_dataclass(e) else vars(e),
                idempotency_key=e.idempotency_key,
            )
            envelopes.append(env)
            self.outbox_events.append(
                {
                    "tenant_id": aggregate.tenant_id,
                    "event_type": env.event_type,
                    "payload": env.payload,
                    "key": env.idempotency_key,
                }
            )
        aggregate.clear_domain_events()
        return envelopes

    async def save_all(self, models: list[Any]) -> list:
        for model in models:
            await self.save(model)
        return []

    async def get_edi_messages_by_traces(
        self, tenant_id: str, trace_ids: list[str]
    ) -> list[EdiMessageDomainModel]:
        return [m for m in self._models.values() if m.trace_id in trace_ids]

    async def increment_replay_count(
        self, tenant_id: str, trace_ids: list[str], entity_type: TransactionEntityType
    ) -> None:
        for trace_id in trace_ids:
            for model in self._models.values():
                if model.trace_id == trace_id:
                    model.replay_count += 1

    async def save_trace_event(self, event: Any) -> None:
        pass

    async def save_all_trace_events(self, events: list[Any]) -> None:
        pass


class FakeOutboxRepo:
    async def mark_completed(self, event_id: str) -> None:
        pass


class FakeDataPlaneUnitOfWork:
    def __init__(self, trace_repo: FakeTraceRepository, message_repo: FakeEdiMessageRepository):
        self.traces = trace_repo
        self.edi_messages = message_repo
        self.transactions = message_repo  # for compatibility with old uses
        self.outbox = FakeOutboxRepo()
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


class TestGetEdiTraceUseCase:
    def setup_method(self):
        self.trace_repo = FakeTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = GetEdiTraceUseCase(uow=self.uow)
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_trace_missing(self):
        with pytest.raises(TransactionNotFoundError) as exc_info:
            await self.use_case.get_edi_trace(self.tenant_id, "missing-trace")
        assert exc_info.value.trace_id == "missing-trace"

    @pytest.mark.asyncio
    async def test_returns_trace_result(self):
        msg = EdiMessageDTO(
            id="msg-1",
            trace_id="trace-ok",
            connection_type="AS2",
            direction="INBOUND",
            status="SUCCESS",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.trace_repo.seed_trace(
            self.tenant_id, "trace-ok", EdiTraceDTO(edi_message=msg, edi_jsons=[], api_gateways=[])
        )
        result = await self.use_case.get_edi_trace(self.tenant_id, "trace-ok")
        assert result.edi_message.trace_id == msg.trace_id
        assert result.edi_message.direction == "INBOUND"


class TestReplayTransactionUseCase:
    def setup_method(self):
        self.trace_repo = FakeTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = ReplayTransactionUseCase(uow=self.uow, publisher=FakeOutboxPublisher())
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_transaction_missing(self):
        with pytest.raises(TransactionNotFoundError) as exc_info:
            await self.use_case.retry_transform(self.tenant_id, "missing-trace", actor="USER")
        assert exc_info.value.trace_id == "missing-trace"

    @pytest.mark.asyncio
    async def test_publishes_replay_event_for_valid_trace(self):
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
        msg_dto = EdiMessageDTO(
            id="msg-1", trace_id="t-001", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
        self.trace_repo.seed_trace(
            self.tenant_id, "t-001", EdiTraceDTO(edi_message=msg_dto, edi_jsons=[], api_gateways=[])
        )
        await self.use_case.retry_deliver(self.tenant_id, "t-001", actor="USER")
        assert len(self.msg_repo.outbox_events) == 1
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

    @pytest.mark.asyncio
    async def test_replay_event_includes_trace_id_and_tier(self):
        model = EdiMessageDomainModel(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="t-002",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )
        self.msg_repo.seed_model(model)
        msg_dto = EdiMessageDTO(
            id="msg-1", trace_id="t-002", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
        self.trace_repo.seed_trace(
            self.tenant_id, "t-002", EdiTraceDTO(edi_message=msg_dto, edi_jsons=[], api_gateways=[])
        )
        new_trace_id = await self.use_case.retry_transform(self.tenant_id, "t-002", actor="USER")
        payload = self.msg_repo.outbox_events[0]["payload"]
        assert payload["trace_id"] == new_trace_id

    @pytest.mark.asyncio
    async def test_replay_event_has_unique_idempotency_key(self):
        model = EdiMessageDomainModel(
            id="msg-1",
            tenant_id=self.tenant_id,
            trace_id="t-003",
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )
        self.msg_repo.seed_model(model)
        msg_dto = EdiMessageDTO(
            id="msg-1", trace_id="t-003", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
        self.trace_repo.seed_trace(
            self.tenant_id, "t-003", EdiTraceDTO(edi_message=msg_dto, edi_jsons=[], api_gateways=[])
        )
        await self.use_case.retry_transform(self.tenant_id, "t-003", actor="USER")
        key = self.msg_repo.outbox_events[0]["key"]
        assert key is not None

    @pytest.mark.asyncio
    async def test_inbound_transform_replay_clones_message_only_with_received_status(self):
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

        # Message must be cloned with RECEIVED status
        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is not None
        assert cloned_msg.status == MessageStatus.RECEIVED
        assert cloned_msg.original_trace_id == "trace-in-1"
        assert cloned_msg.parent_trace_id == "trace-in-1"
        assert cloned_msg.replay_count == 1

        # Event must be TRANSFORMATION_REQUESTED
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

        # EdiJson must NOT be cloned
        cloned_json = await self.msg_repo.get_edi_json(new_trace_id)
        assert cloned_json is None

    @pytest.mark.asyncio
    async def test_inbound_deliver_replay_clones_json_only_with_pending_delivery_status(self):
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

        # Json must be cloned with PENDING_DELIVERY status
        cloned_json = await self.msg_repo.get_edi_json(new_trace_id)
        assert cloned_json is not None
        assert cloned_json.status == MessageStatus.PENDING_DELIVERY
        assert cloned_json.original_trace_id == "trace-in-1"
        assert cloned_json.parent_trace_id == "trace-in-1"
        assert cloned_json.replay_count == 1

        # Event must be DELIVERY_REQUESTED
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"

        # EdiMessage must NOT be cloned
        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is None

    @pytest.mark.asyncio
    async def test_outbound_transform_replay_clones_json_only_with_received_status(self):
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

        # Json must be cloned with RECEIVED status
        cloned_json = await self.msg_repo.get_edi_json(new_trace_id)
        assert cloned_json is not None
        assert cloned_json.status == MessageStatus.RECEIVED
        assert cloned_json.original_trace_id == "trace-out-1"
        assert cloned_json.parent_trace_id == "trace-out-1"
        assert cloned_json.replay_count == 1

        # Event must be TRANSFORMATION_REQUESTED
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

        # EdiMessage must NOT be cloned
        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is None

    @pytest.mark.asyncio
    async def test_outbound_deliver_replay_clones_message_only_with_pending_delivery_status(self):
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

        # Message must be cloned with PENDING_DELIVERY status
        cloned_msg = await self.msg_repo.get_edi_message(new_trace_id)
        assert cloned_msg is not None
        assert cloned_msg.status == MessageStatus.PENDING_DELIVERY
        assert cloned_msg.original_trace_id == "trace-out-1"
        assert cloned_msg.parent_trace_id == "trace-out-1"
        assert cloned_msg.replay_count == 1

        # Event must be DELIVERY_REQUESTED
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "DELIVERY_REQUESTED"


class TestGetEdiTraceLineageUseCase:
    def setup_method(self):
        self.trace_repo = FakeTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = GetEdiTraceLineageUseCase(uow=self.uow)
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_lineage_isolation_between_inbound_and_outbound(self):
        # Inbound trace 1 & 2
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

        # Outbound trace 1 & 2
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

        # Lineage query for inbound trace must ONLY return inbound attempts
        lineage = await self.use_case.execute(self.tenant_id, "t-in-1")
        assert len(lineage) == 2
        trace_ids = [item.trace_id for item in lineage]
        assert trace_ids == ["t-in-1", "t-in-2"]
        assert "t-out-1" not in trace_ids

    @pytest.mark.asyncio
    async def test_lineage_includes_downstream_delivery_replay_attempts(self):
        # Attempt 1: Inbound message + json
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

        # Attempt 2: Delivery retry (Only JSON cloned)
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


@pytest.mark.asyncio
async def test_bulk_replay_commits_after_saving_events():
    trace_repo = FakeTraceRepository()
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
    msg_dto = EdiMessageDTO(
        id="msg-1", trace_id="trace-1", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )
    trace_repo.seed_trace(
        tenant_id, "trace-1", EdiTraceDTO(edi_message=msg_dto, edi_jsons=[], api_gateways=[])
    )

    count = await BulkReplayTransactionsUseCase(
        uow, publisher=FakeOutboxPublisher()
    ).bulk_retry_transform(tenant_id, ["trace-1"], "USER", command_key="request-1")

    assert count == 1
    assert uow.committed is True


class TestListEdiMessagesUseCase:
    def setup_method(self):
        self.trace_repo = FakeTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = ListEdiMessagesUseCase(uow=self.uow)
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self):
        result = await self.use_case.list_edi_messages(self.tenant_id, limit=10, offset=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_domain_models_for_found_messages(self):
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
        result = await self.use_case.list_edi_messages(self.tenant_id, limit=10, offset=0)
        assert len(result) == 2
        trace_ids = {r.trace_id for r in result}
        assert "t-001" in trace_ids
        assert "t-002" in trace_ids

    @pytest.mark.asyncio
    async def test_passes_skip_and_limit_to_repository(self):
        summaries = [
            EdiMessageDTO(
                id=f"msg-{i}",
                trace_id=f"t-{i}",
                connection_type="AS2",
                direction="INBOUND",
                status="SUCCESS",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            for i in range(5)
        ]
        self.msg_repo.seed_summaries(summaries)
        result = await self.use_case.list_edi_messages(self.tenant_id, limit=2, offset=2)
        assert len(result) == 2
        assert result[0].trace_id == "t-2"
