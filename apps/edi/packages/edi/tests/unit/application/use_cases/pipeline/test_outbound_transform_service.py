from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

"""
Unit tests for the OutboundTransformUseCase.
Uses Fake Data Plane Unit Of Work and Fake Transformer.
"""

import pytest

from edi.application.use_cases.pipeline.dispatch_outbound_transform_use_case import (
    DispatchOutboundTransformUseCase,
)
from edi.config.settings import AppSettings
from edi.domain.direction import MessageDirection
from edi.domain.events import PipelineEventType
from edi.domain.status import MessageStatus
from edi.testing.fakes.pipeline_fakes import FakeDataPlaneUnitOfWork, FakeTransformerAdapter

pytestmark = pytest.mark.asyncio


import typing


class FakeSettings(AppSettings):
    @classmethod
    def create(cls, env="T", heavy_compute=False) -> "FakeSettings":
        return cls.model_construct(
            edi_environment=env,
            enable_heavy_compute_queue=heavy_compute,
        )


def make_use_case(
    uow: FakeDataPlaneUnitOfWork | None = None,
    transformer: FakeTransformerAdapter | None = None,
    settings: FakeSettings | None = None,
) -> DispatchOutboundTransformUseCase:

    u = uow or FakeDataPlaneUnitOfWork()
    uow_casted = typing.cast(DataPlaneUnitOfWorkPort, u)
    t = transformer or FakeTransformerAdapter()
    s = settings or FakeSettings.create()
    s_casted = typing.cast(AppSettings, s)
    return DispatchOutboundTransformUseCase(uow=uow_casted, transformer=t, settings=s_casted)


async def test_outbound_transform_success() -> None:
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()
    trace_id = "trace-123"

    # Seed data
    uow.repository.edi_json[trace_id] = {
        "trace_id": trace_id,
        "payload": {"data": "test"},
        "trading_partner_id": "tp1",
        "tenant_id": "tenant1",
        "business_metadata": {},
        "transaction_type": "850",
    }

    uow.repository.routes.append(
        {
            "direction": "OUTBOUND",
            "as2_partner_id": "tp1",
        }
    )

    uow.repository.outbound_edi_headers["tp1"] = {
        "trading_partner_id": "tp1",
        "default_standard": "X12",
        "isa_sender_id": "SENDER1",
        "isa_receiver_id": "RECEIVER1",
        "gs_sender_id": "GS_SENDER",
        "gs_receiver_id": "GS_RECEIVER",
    }

    use_case = make_use_case(uow=uow, transformer=transformer)
    await use_case.execute(trace_id)

    # Assertions
    saved_edi = uow.repository.edi_messages.get(trace_id)
    assert saved_edi is not None
    assert saved_edi["direction"] == MessageDirection.OUTBOUND
    assert saved_edi["status"] == MessageStatus.PENDING_DELIVERY
    assert saved_edi["trading_partner_id"] == "tp1"
    assert saved_edi["connection_type"] == "AS2"
    assert saved_edi["sender_id"] == "SENDER1"

    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == PipelineEventType.TRANSFORM_COMPLETED
    assert event["payload"]["trace_id"] == trace_id
    assert event["payload"]["trading_partner_id"] == "tp1"


async def test_outbound_transform_heavy_compute_offload() -> None:
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()
    settings = FakeSettings.create(heavy_compute=True)
    trace_id = "trace-456"

    # Seed data
    uow.repository.edi_json[trace_id] = {
        "trace_id": trace_id,
        "payload": {"data": "heavy"},
        "trading_partner_id": "tp2",
        "tenant_id": "tenant1",
        "business_metadata": {},
        "transaction_type": "855",
    }

    uow.repository.routes.append(
        {
            "direction": "OUTBOUND",
            "sftp_partner_id": "tp2",
        }
    )

    uow.repository.outbound_edi_headers["tp2"] = {
        "trading_partner_id": "tp2",
        "default_standard": "EDIFACT",
    }

    use_case = make_use_case(uow=uow, transformer=transformer, settings=settings)
    await use_case.execute(trace_id)

    # Assertions - should not save EDI message since it's offloaded
    assert trace_id not in uow.repository.edi_messages

    # But it should append to outbox
    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == PipelineEventType.COMPUTE_TRANSFORM_EVENT
    assert event["payload"]["trace_id"] == trace_id


async def test_outbound_transform_missing_json_raises() -> None:
    uow = FakeDataPlaneUnitOfWork()
    use_case = make_use_case(uow=uow)

    with pytest.raises(ValueError, match="No EdiJson record found"):
        await use_case.execute("missing-trace")


async def test_outbound_transform_missing_route_raises() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-noroute"

    uow.repository.edi_json[trace_id] = {
        "trace_id": trace_id,
        "payload": {"data": "test"},
        "trading_partner_id": "tp-missing",
        "tenant_id": "tenant1",
        "business_metadata": {},
    }

    use_case = make_use_case(uow=uow)

    with pytest.raises(ValueError, match="Unsuccessful route/header lookup for trace_id="):
        await use_case.execute(trace_id)


async def test_outbound_transform_resolves_partner_from_routing_meta() -> None:
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()
    trace_id = "trace-routing-meta"

    # Seed data with partner ID only in routing metadata
    uow.repository.edi_json[trace_id] = {
        "trace_id": trace_id,
        "payload": {"data": "test"},
        "trading_partner_id": None,
        "tenant_id": "tenant1",
        "business_metadata": {"_routing": {"trading_partner_id": "tp-meta"}},
        "transaction_type": "810",
    }

    uow.repository.routes.append(
        {
            "direction": "OUTBOUND",
            "as2_partner_id": "tp-meta",
        }
    )

    uow.repository.outbound_edi_headers["tp-meta"] = {
        "trading_partner_id": "tp-meta",
        "connection_type": "VAN",
    }

    use_case = make_use_case(uow=uow, transformer=transformer)
    await use_case.execute(trace_id)

    saved_edi = uow.repository.edi_messages.get(trace_id)
    assert saved_edi is not None
    assert saved_edi["trading_partner_id"] == "tp-meta"
    assert saved_edi["connection_type"] == "VAN"
