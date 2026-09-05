import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id

from edi.application.dtos.trace import EdiTraceDTO
from edi.application.dtos.transactions import EdiMessageDTO
from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
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
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiMessageDomainModel


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
        self.outbox_events: list[dict[str, Any]] = []

    def seed_summaries(self, summaries: list[EdiMessageDTO]):
        self._messages = summaries

    def seed_model(self, model: EdiMessageDomainModel):
        self._models[model.id] = model

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        **kwargs,
    ) -> list[EdiMessageDTO]:
        return self._messages[offset : offset + limit]

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

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
        for model in self._models.values():
            if model.trace_id == trace_id:
                return model
        return None

    async def save(self, model: Any) -> None:
        for e in model.domain_events:
            event_type = getattr(e, "event_type", "edi.transaction.replay_requested")
            if dataclasses.is_dataclass(e):
                payload = dataclasses.asdict(e)
            else:
                payload = getattr(e, "model_dump", lambda ev=e: vars(ev))()
            key = getattr(e, "explicit_idempotency_key", None)
            self.outbox_events.append(
                {
                    "tenant_id": model.tenant_id,
                    "event_type": event_type,
                    "payload": payload,
                    "key": key,
                }
            )
        model.clear_domain_events()


class FakeDataPlaneUnitOfWork:
    def __init__(self, trace_repo: FakeTraceRepository, message_repo: FakeEdiMessageRepository):
        self.traces = trace_repo
        self.edi_messages = message_repo
        self.transactions = message_repo  # for compatibility with old uses
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
        self.tenant_id = generate_id(IdentityIdPrefix.TENANT)

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
        self.use_case = ReplayTransactionUseCase(uow=self.uow)
        self.tenant_id = generate_id(IdentityIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_transaction_missing(self):
        with pytest.raises(TransactionNotFoundError) as exc_info:
            await self.use_case.replay_transaction(
                self.tenant_id, "missing-trace", tier="transform"
            )
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
        self.msg_repo.seed_model(model)
        msg_dto = EdiMessageDTO(
            id="msg-1", trace_id="t-001", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
        self.trace_repo.seed_trace(
            self.tenant_id, "t-001", EdiTraceDTO(edi_message=msg_dto, edi_jsons=[], api_gateways=[])
        )
        await self.use_case.replay_transaction(self.tenant_id, "t-001", tier="deliver")
        assert len(self.msg_repo.outbox_events) == 1
        event = self.msg_repo.outbox_events[0]
        assert event["event_type"] == "edi.transaction.replay_requested"

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
        await self.use_case.replay_transaction(self.tenant_id, "t-002", tier="transform")
        payload = self.msg_repo.outbox_events[0]["payload"]
        assert payload["trace_id"] == "t-002"
        assert payload["tier"] == "transform"

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
        await self.use_case.replay_transaction(self.tenant_id, "t-003", tier="transform")
        key = self.msg_repo.outbox_events[0]["key"]
        assert "t-003" in key


@pytest.mark.asyncio
async def test_bulk_replay_commits_after_saving_events():
    trace_repo = FakeTraceRepository()
    msg_repo = FakeEdiMessageRepository()
    uow = FakeDataPlaneUnitOfWork(trace_repo, msg_repo)
    tenant_id = generate_id(IdentityIdPrefix.TENANT)

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

    count = await BulkReplayTransactionsUseCase(uow).bulk_replay_transactions(
        tenant_id, ["trace-1"], "raw", command_key="request-1"
    )

    assert count == 1
    assert uow.committed is True


class TestListEdiMessagesUseCase:
    def setup_method(self):
        self.trace_repo = FakeTraceRepository()
        self.msg_repo = FakeEdiMessageRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.trace_repo, self.msg_repo)
        self.use_case = ListEdiMessagesUseCase(uow=self.uow)
        self.tenant_id = generate_id(IdentityIdPrefix.TENANT)

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
