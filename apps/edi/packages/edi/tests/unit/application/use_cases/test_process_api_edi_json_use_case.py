"""
Layer 2 — Application Use Case Tests: ProcessApiEdiJsonUseCase.

This is the Outbound API ingestion use case. It:
1. Resolves transaction_type from payload if not supplied in the command
2. Extracts business_metadata using MetadataExtractorService
3. Persists EdiJson via UoW.edi_jsons.save
4. Publishes a TRANSFORMATION_REQUESTED outbox event

We inject a port-conforming in-memory UoW — no DB, no HTTP, no patches.
"""

from typing import cast

import pytest
from seedwork.events import EventEnvelope
from seedwork.utils import generate_id

from edi.application.use_cases.process_api_edi_json_use_case import (
    ProcessApiEdiJsonCommand,
    ProcessApiEdiJsonUseCase,
)
from edi.domain.routing.enums import Direction
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.enums import RecordStatus
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from edi.testing.fakes.pipeline_fakes import FakeOutboxPublisher

TP_001 = generate_id("tp")
TP_007 = generate_id("tp")
TP_META = generate_id("tp")
TP_X = generate_id("tp")


# ---------------------------------------------------------------------------
# Fake port implementations
# ---------------------------------------------------------------------------


class FakeEdiJsonRepository:
    """Minimal EdiJsonRepositoryPort conforming in-memory store."""

    def __init__(self) -> None:
        self.created_edi_jsons: list[dict[str, object]] = []
        self.outbox_events: list[dict[str, object]] = []

    async def save(self, aggregate: EdiJson) -> list[EventEnvelope]:
        self.created_edi_jsons.append(
            {
                "tenant_id": aggregate.tenant_id,
                "payload": {
                    "trace_id": aggregate.trace_id,
                    "direction": aggregate.direction.value
                    if aggregate.direction is not None
                    else None,
                    "transaction_type": aggregate.transaction_type,
                    "business_metadata": aggregate.business_metadata,
                    "payload": aggregate.payload,
                    "status": aggregate.status.value if aggregate.status is not None else None,
                },
            }
        )
        for event in aggregate.domain_events:
            self.outbox_events.append(
                {
                    "tenant_id": aggregate.tenant_id,
                    "event_type": event.event_name,
                    "payload": event,
                    "idempotency_key": event.idempotency_key,
                }
            )
        aggregate.clear_domain_events()
        return []


class FakeTraceRepository:
    """Minimal TraceRepositoryPort-conforming in-memory store."""

    async def get_trace(
        self,
        tenant_id: str,
        trace_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> None:
        _ = (tenant_id, trace_id, hydrate_payloads)
        return None


class FakeOutboxRepo:
    async def mark_completed(self, event_id: str) -> None:
        _ = event_id


class FakeDataPlaneUnitOfWork:
    def __init__(self, repo: FakeEdiJsonRepository) -> None:
        self.edi_jsons = repo
        self.traces = FakeTraceRepository()
        self.outbox = FakeOutboxRepo()
        self.committed = False

    async def __aenter__(self) -> "FakeDataPlaneUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        _ = args

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessApiEdiJsonUseCaseHappyPath:
    def setup_method(self) -> None:
        self.repo = FakeEdiJsonRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ProcessApiEdiJsonUseCase(
            uow=cast(DataPlaneUnitOfWorkPort, self.uow),
            publisher=FakeOutboxPublisher(),
        )

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
        assert event["event_type"] == "TRANSFORMATION_REQUESTED"

    @pytest.mark.asyncio
    async def test_fake_preserves_event_idempotency_key(self):

        aggregate = EdiJson(
            id="json-1",
            tenant_id="ten_001",
            trace_id="trace-1",
            direction=Direction.OUTBOUND,
            status=RecordStatus.RECEIVED,
            payload={},
        )
        aggregate.request_transformation(idempotency_key="request-1")

        await self.repo.save(aggregate)

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
    def setup_method(self) -> None:
        self.repo = FakeEdiJsonRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ProcessApiEdiJsonUseCase(
            uow=cast(DataPlaneUnitOfWorkPort, self.uow),
            publisher=FakeOutboxPublisher(),
        )

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
    async def test_resolves_transaction_type_from_stedi_interchange_structure(self):
        """Resolves via interchange > transaction_sets > heading > transaction_set_header_ST*."""
        cmd = ProcessApiEdiJsonCommand(
            tenant_id="ten_001",
            trading_partner_id=TP_001,
            payload={
                "interchange": {
                    "transaction_sets": [
                        {
                            "heading": {
                                "transaction_set_header_ST": {
                                    "transaction_set_identifier_code": "850"
                                }
                            }
                        }
                    ]
                }
            },
            transaction_type=None,
        )
        await self.use_case.process_api_edi_json(cmd)
        saved_type = self.repo.created_edi_jsons[0]["payload"]["transaction_type"]
        assert saved_type == "850"

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
    def setup_method(self) -> None:
        self.repo = FakeEdiJsonRepository()
        self.uow = FakeDataPlaneUnitOfWork(self.repo)
        self.use_case = ProcessApiEdiJsonUseCase(
            uow=cast(DataPlaneUnitOfWorkPort, self.uow),
            publisher=FakeOutboxPublisher(),
        )

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
