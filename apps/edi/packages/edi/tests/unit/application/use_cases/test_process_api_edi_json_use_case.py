"""
Layer 2 — Application Use Case Tests: ProcessApiEdiJsonUseCase.

This is the Outbound API ingestion use case. It:
1. Resolves transaction_type from payload if not supplied in the command
2. Extracts business_metadata using MetadataExtractorService
3. Persists EdiJson via UoW.transactions.create_edi_json
4. Publishes a TRANSFORM_EVENT outbox event

We inject a port-conforming in-memory UoW — no DB, no HTTP, no patches.
"""

from typing import Any

import pytest
from seedwork.utils import generate_id

TP_001 = generate_id("tp")
TP_007 = generate_id("tp")
TP_META = generate_id("tp")
TP_X = generate_id("tp")

from edi.application.dto import ProcessApiEdiJsonCommand
from edi.application.use_cases.process_api_edi_json_use_case import ProcessApiEdiJsonUseCase

# ---------------------------------------------------------------------------
# Fake port implementations
# ---------------------------------------------------------------------------


class FakeTransactionRepository:
    """Minimal TransactionRepositoryPort conforming in-memory store."""

    def __init__(self):
        self.created_edi_jsons: list[dict[str, Any]] = []
        self.outbox_events: list[dict[str, Any]] = []

    async def save_json(self, aggregate: Any) -> None:
        self.created_edi_jsons.append(
            {
                "tenant_id": aggregate.tenant_id,
                "payload": {
                    "trace_id": aggregate.trace_id,
                    "direction": aggregate.direction.value
                    if hasattr(aggregate.direction, "value")
                    else aggregate.direction,
                    "transaction_type": aggregate.transaction_type,
                    "business_metadata": aggregate.business_metadata,
                    "payload": aggregate.payload,
                    "status": aggregate.status.value
                    if hasattr(aggregate.status, "value")
                    else aggregate.status,
                },
            }
        )
        for event in aggregate.domain_events:
            self.outbox_events.append(
                {
                    "tenant_id": aggregate.tenant_id,
                    "event_type": str(event.__class__.__name__),
                    "payload": event,
                    "idempotency_key": event.idempotency_key,
                }
            )
        aggregate.clear_domain_events()


class FakeDataPlaneUnitOfWork:
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
# Tests
# ---------------------------------------------------------------------------


class TestProcessApiEdiJsonUseCaseHappyPath:
    def setup_method(self):
        self.repo = FakeTransactionRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ProcessApiEdiJsonUseCase(uow=self.uow)

    @pytest.mark.asyncio
    async def test_returns_a_trace_id_string(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "850", "heading": {}},
            transaction_type="850",
        )
        trace_id = await self.use_case.process_api_edi_json(cmd)
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    @pytest.mark.asyncio
    async def test_creates_edi_json_record(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "850"},
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        assert len(self.repo.created_edi_jsons) == 1
        saved = self.repo.created_edi_jsons[0]
        assert saved["tenant_id"] == "ten_001"

    @pytest.mark.asyncio
    async def test_saves_edi_json_with_received_status(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "850"},
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        payload = self.repo.created_edi_jsons[0]["payload"]
        assert payload["status"] == "RECEIVED"

    @pytest.mark.asyncio
    async def test_saves_edi_json_with_outbound_direction(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "850"},
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        payload = self.repo.created_edi_jsons[0]["payload"]
        assert payload["direction"] == "OUTBOUND"

    @pytest.mark.asyncio
    async def test_routing_metadata_is_injected(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_007,
            payload={"transaction_type": "850"},
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        bm = self.repo.created_edi_jsons[0]["payload"]["business_metadata"]
        assert bm["_routing"]["trading_partner_id"] == TP_007

    @pytest.mark.asyncio
    async def test_publishes_transform_event_to_outbox(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "850"},
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        assert len(self.repo.outbox_events) == 1
        event = self.repo.outbox_events[0]
        assert "TRANSFORM" in event["event_type"].upper()

    @pytest.mark.asyncio
    async def test_fake_preserves_event_idempotency_key(self):
        from edi.domain.events import TransformRequestedEvent
        from edi.domain.models.base import Direction, RecordStatus
        from edi.domain.models.transactions import EdiJsonDomainModel

        aggregate = EdiJsonDomainModel(
            id="json-1",
            tenant_id="ten_001",
            trace_id="trace-1",
            direction=Direction.OUTBOUND,
            status=RecordStatus.RECEIVED,
            payload={},
        )
        aggregate.add_domain_event(
            TransformRequestedEvent(
                trace_id="trace-1",
                tenant_id="ten_001",
                explicit_idempotency_key="request-1",
            )
        )

        await self.repo.save_json(aggregate)

        key = self.repo.outbox_events[0]["idempotency_key"]
        assert key == "request-1"
        assert key != "trace-1"

    @pytest.mark.asyncio
    async def test_commits_unit_of_work(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "850"},
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        assert self.uow.committed is True


class TestProcessApiEdiJsonUseCaseTransactionTypeResolution:
    def setup_method(self):
        self.repo = FakeTransactionRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ProcessApiEdiJsonUseCase(uow=self.uow)

    @pytest.mark.asyncio
    async def test_uses_explicit_transaction_type_from_command(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"whatever": "value"},
            transaction_type="810",
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type == "810"

    @pytest.mark.asyncio
    async def test_resolves_transaction_type_from_payload_transaction_type_key(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"transaction_type": "997"},
            transaction_type=None,
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type == "997"

    @pytest.mark.asyncio
    async def test_resolves_transaction_type_from_st_header(self):
        """Resolves via heading > transaction_set_header_ST* > transaction_set_identifier_code."""
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={
                "heading": {"transaction_set_header_ST": {"transaction_set_identifier_code": "204"}}
            },
            transaction_type=None,
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type == "204"

    @pytest.mark.asyncio
    async def test_resolves_transaction_type_from_st_segment(self):
        """Resolves via raw ST.ST01 segment when heading approach fails."""
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"ST": {"ST01": "214"}},
            transaction_type=None,
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type == "214"

    @pytest.mark.asyncio
    async def test_resolves_transaction_type_from_list_payload_first_item(self):
        """When payload is a list, type is resolved from the first element."""
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload=[
                {"transaction_type": "850", "heading": {"BEG": {"BEG03": "PO-001"}}},
                {"transaction_type": "850", "heading": {"BEG": {"BEG03": "PO-002"}}},
            ],
            transaction_type=None,
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type == "850"

    @pytest.mark.asyncio
    async def test_saves_none_transaction_type_when_unresolvable(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={"no_type_here": True},
            transaction_type=None,
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type is None


class TestProcessApiEdiJsonUseCaseListPayload:
    def setup_method(self):
        self.repo = FakeTransactionRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ProcessApiEdiJsonUseCase(uow=self.uow)

    @pytest.mark.asyncio
    async def test_handles_list_payload_with_multiple_items(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload=[
                {"transaction_type": "850", "heading": {"BEG": {"BEG03": "PO-A"}}},
                {"transaction_type": "850", "heading": {"BEG": {"BEG03": "PO-B"}}},
            ],
            transaction_type="850",
        )
        trace_id = await self.use_case.process_api_edi_json(cmd)
        assert trace_id  # no crash; returns a valid trace ID

    @pytest.mark.asyncio
    async def test_business_metadata_deduplicates_values_across_list_items(self):
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload=[
                {"transaction_type": "850", "heading": {"BEG": {"BEG03": "SAME-PO"}}},
                {"transaction_type": "850", "heading": {"BEG": {"BEG03": "SAME-PO"}}},
            ],
            transaction_type="850",
        )
        await self.use_case.process_api_edi_json(cmd)
        bm = self.repo.created_edi_jsons[0]["payload"]["business_metadata"]
        # Same PO value from both items → deduped into single scalar
        assert bm.get("po_number") == "SAME-PO"
