"""
Layer 2 — Application Use Case Tests: Transaction use cases.

Uses a minimal FakeDataPlaneUoW that exposes `transactions` as an
InMemoryRepositoryAdapter. All tests are pure unit tests — no DB, no HTTP,
no patches/mocks. This is hexagonal architecture: inject a Port-conforming
fake and assert on observable behavior.
"""

import dataclasses
from dataclasses import dataclass
from typing import Any

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id

from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.get_transaction_use_case import (
    GetTransactionUseCase,
)
from edi.application.use_cases.transactions.list_transactions_use_case import (
    ListTransactionsUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from edi.domain.exceptions import TransactionNotFoundError

# ---------------------------------------------------------------------------
# Fake infrastructure — Port-conforming in-memory implementations
# ---------------------------------------------------------------------------


@dataclass
class FakeEdiMessage:
    trace_id: str
    direction: str = "INBOUND"
    connection_type: str = "AS2"
    sender_id: str = "SENDER"
    receiver_id: str = "RECEIVER"
    gs_sender_id: str = "GS_S"
    gs_receiver_id: str = "GS_R"
    status: str = "RECEIVED"
    edi_data: str = "ISA*..."
    parent_trace_id: str | None = None
    created_at: Any = None
    trading_partner_id: str | None = None

    def __post_init__(self):
        if self.created_at is None:
            from datetime import UTC, datetime

            self.created_at = datetime.now(UTC)

    @property
    def id(self):
        import uuid

        return uuid.uuid5(uuid.NAMESPACE_DNS, self.trace_id)


@dataclass
class FakeTransactionResult:
    edi_message: FakeEdiMessage | None
    edi_jsons: list[Any] | None = None
    api_gateways: list[Any] | None = None

    def __post_init__(self):
        if self.edi_jsons is None:
            self.edi_jsons = []
        if self.api_gateways is None:
            self.api_gateways = []


@dataclass
class FakeTransactionSummary:
    trace_id: str
    transaction_type: str = "850"
    direction: str = "OUTBOUND"
    trading_partner_id: str | None = None
    status: str = "RECEIVED"
    received_at: Any = None

    def __post_init__(self):
        if self.received_at is None:
            from datetime import UTC, datetime

            self.received_at = datetime.now(UTC)


class FakeRoutingContextResolver:
    def __init__(self, tenant_id: str, channel: str):
        self._tenant_id = tenant_id
        self._channel = channel
        self.resolved = False

    async def resolve_routing_context(
        self, edi_message: Any, edi_jsons: list[Any]
    ) -> tuple[str, str]:
        self.resolved = True
        return self._tenant_id, self._channel


class FakeTransactionRepository:
    def __init__(self):
        self._transactions: dict[str, FakeTransactionResult] = {}
        self._summaries: list[FakeTransactionSummary] = []
        self.outbox_events: list[dict[str, Any]] = []

    def seed_transaction(self, tenant_id: str, trace_id: str, result: FakeTransactionResult):
        self._transactions[f"{tenant_id}:{trace_id}"] = result

    def seed_summaries(self, summaries: list[FakeTransactionSummary]):
        self._summaries = summaries

    async def get_transaction(self, tenant_id: str, trace_id: str) -> FakeTransactionResult | None:
        return self._transactions.get(f"{tenant_id}:{trace_id}")

    async def list_transactions(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        **kwargs,
    ) -> list[FakeTransactionSummary]:
        return self._summaries[offset : offset + limit]

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

    async def get_edi_message(self, trace_id: str) -> Any:
        from edi.domain.models.base import Direction, RecordStatus
        from edi.domain.models.transactions import EdiMessageDomainModel

        # Mock returning an aggregate
        return EdiMessageDomainModel(
            id="fake_id",
            tenant_id="tenant",
            trace_id=trace_id,
            direction=Direction.INBOUND,
            status=RecordStatus.SUCCESS,
        )

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
    """Port-conforming in-memory UoW that wires `transactions`."""

    def __init__(self, repo: FakeTransactionRepository):
        self.transactions = repo
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


# ---------------------------------------------------------------------------
# GetTransactionUseCase
# ---------------------------------------------------------------------------


class TestGetTransactionUseCase:
    def setup_method(self):
        self.repo = FakeTransactionRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = GetTransactionUseCase(uow=self.uow)
        self.tenant_id = generate_id(IdentityIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_transaction_missing(self):
        with pytest.raises(TransactionNotFoundError) as exc_info:
            await self.use_case.get_transaction(self.tenant_id, "missing-trace")
        assert exc_info.value.trace_id == "missing-trace"

    @pytest.mark.asyncio
    async def test_raises_not_found_when_edi_message_is_none(self):
        self.repo.seed_transaction(
            self.tenant_id, "trace-123", FakeTransactionResult(edi_message=None)
        )
        with pytest.raises(TransactionNotFoundError):
            await self.use_case.get_transaction(self.tenant_id, "trace-123")

    @pytest.mark.asyncio
    async def test_returns_transaction_detail_result(self):
        msg = FakeEdiMessage(trace_id="trace-ok", direction="INBOUND")
        self.repo.seed_transaction(
            self.tenant_id, "trace-ok", FakeTransactionResult(edi_message=msg)
        )
        result = await self.use_case.get_transaction(self.tenant_id, "trace-ok")
        assert result.edi_message["trace_id"] == str(msg.trace_id)
        assert result.edi_message["direction"] == "INBOUND"

    @pytest.mark.asyncio
    async def test_returns_empty_edi_json_list_when_none(self):
        msg = FakeEdiMessage(trace_id="trace-ok")
        self.repo.seed_transaction(
            self.tenant_id, "trace-ok", FakeTransactionResult(edi_message=msg)
        )
        result = await self.use_case.get_transaction(self.tenant_id, "trace-ok")
        assert result.edi_json == []

    @pytest.mark.asyncio
    async def test_returns_empty_api_gateway_list_when_none(self):
        msg = FakeEdiMessage(trace_id="trace-ok")
        self.repo.seed_transaction(
            self.tenant_id, "trace-ok", FakeTransactionResult(edi_message=msg)
        )
        result = await self.use_case.get_transaction(self.tenant_id, "trace-ok")
        assert result.api_gateway == []

    @pytest.mark.asyncio
    async def test_trading_partner_name_is_none_without_resolver(self):
        msg = FakeEdiMessage(trace_id="trace-ok")
        self.repo.seed_transaction(
            self.tenant_id, "trace-ok", FakeTransactionResult(edi_message=msg)
        )
        result = await self.use_case.get_transaction(self.tenant_id, "trace-ok")
        assert result.trading_partner_name is None

    @pytest.mark.asyncio
    async def test_uses_routing_resolver_when_provided(self):
        msg = FakeEdiMessage(trace_id="trace-ok")
        self.repo.seed_transaction(
            self.tenant_id, "trace-ok", FakeTransactionResult(edi_message=msg)
        )

        fake_resolver = FakeRoutingContextResolver("TradingCo", "AS2")

        result = await self.use_case.get_transaction(
            self.tenant_id, "trace-ok", routing_resolver=fake_resolver
        )
        assert result.trading_partner_name == "TradingCo"
        assert fake_resolver.resolved is True


# ---------------------------------------------------------------------------
# ReplayTransactionUseCase
# ---------------------------------------------------------------------------


class TestReplayTransactionUseCase:
    def setup_method(self):
        self.repo = FakeTransactionRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
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
    async def test_raises_not_found_when_edi_message_is_none(self):
        self.repo.seed_transaction(self.tenant_id, "t-001", FakeTransactionResult(edi_message=None))
        with pytest.raises(TransactionNotFoundError):
            await self.use_case.replay_transaction(self.tenant_id, "t-001", tier="transform")

    @pytest.mark.asyncio
    async def test_publishes_replay_event_for_valid_trace(self):
        msg = FakeEdiMessage(trace_id="t-001")
        self.repo.seed_transaction(self.tenant_id, "t-001", FakeTransactionResult(edi_message=msg))
        await self.use_case.replay_transaction(self.tenant_id, "t-001", tier="deliver")
        assert len(self.repo.outbox_events) == 1
        event = self.repo.outbox_events[0]
        assert event["event_type"] == "edi.transaction.replay_requested"

    @pytest.mark.asyncio
    async def test_replay_event_includes_trace_id_and_tier(self):
        msg = FakeEdiMessage(trace_id="t-002")
        self.repo.seed_transaction(self.tenant_id, "t-002", FakeTransactionResult(edi_message=msg))
        await self.use_case.replay_transaction(self.tenant_id, "t-002", tier="transform")
        payload = self.repo.outbox_events[0]["payload"]
        assert payload["trace_id"] == "t-002"
        assert payload["tier"] == "transform"

    @pytest.mark.asyncio
    async def test_replay_event_has_unique_idempotency_key(self):
        msg = FakeEdiMessage(trace_id="t-003")
        self.repo.seed_transaction(self.tenant_id, "t-003", FakeTransactionResult(edi_message=msg))
        await self.use_case.replay_transaction(self.tenant_id, "t-003", tier="transform")
        key = self.repo.outbox_events[0]["key"]
        assert "t-003" in key  # key is prefixed with trace_id


@pytest.mark.asyncio
async def test_bulk_replay_commits_after_saving_events():
    repository = FakeTransactionRepository()
    uow = FakeDataPlaneUnitOfWork(repository)
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    repository.seed_transaction(
        tenant_id,
        "trace-1",
        FakeTransactionResult(edi_message=FakeEdiMessage(trace_id="trace-1")),
    )

    count = await BulkReplayTransactionsUseCase(uow).bulk_replay_transactions(
        tenant_id, ["trace-1"], "raw", command_key="request-1"
    )

    assert count == 1
    assert uow.committed is True


# ---------------------------------------------------------------------------
# ListTransactionsUseCase
# ---------------------------------------------------------------------------


class TestListTransactionsUseCase:
    def setup_method(self):
        self.repo = FakeTransactionRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ListTransactionsUseCase(uow=self.uow)
        self.tenant_id = generate_id(IdentityIdPrefix.TENANT)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_transactions(self):
        result = await self.use_case.list_transactions(self.tenant_id, skip=0, limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_domain_models_for_found_transactions(self):
        self.repo.seed_summaries(
            [
                FakeTransactionSummary(trace_id="t-001", transaction_type="850"),
                FakeTransactionSummary(trace_id="t-002", transaction_type="810"),
            ]
        )
        result = await self.use_case.list_transactions(self.tenant_id, skip=0, limit=10)
        assert len(result) == 2
        trace_ids = {r.trace_id for r in result}
        assert "t-001" in trace_ids
        assert "t-002" in trace_ids

    @pytest.mark.asyncio
    async def test_passes_skip_and_limit_to_repository(self):
        summaries = [FakeTransactionSummary(trace_id=f"t-{i}") for i in range(5)]
        self.repo.seed_summaries(summaries)
        result = await self.use_case.list_transactions(self.tenant_id, skip=2, limit=2)
        assert len(result) == 2
        assert result[0].trace_id == "t-2"

    @pytest.mark.asyncio
    async def test_result_trace_ids_match_summaries(self):
        self.repo.seed_summaries([FakeTransactionSummary(trace_id="unique-trace")])
        result = await self.use_case.list_transactions(self.tenant_id, skip=0, limit=10)
        assert result[0].trace_id == "unique-trace"
