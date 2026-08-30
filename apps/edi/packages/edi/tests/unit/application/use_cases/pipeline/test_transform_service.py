"""
Unit tests for InboundTransformUseCase — verifies inbound EDI→JSON transformation.
All test doubles are imported from fakes.py (DRY). No mock library used.
"""

import pytest

from edi.domain.direction import MessageDirection
from edi.domain.events import PipelineEventType
from edi.domain.status import MessageStatus
from edi.testing.fakes.pipeline_fakes import FakeDataPlaneUnitOfWork, FakeTransformerAdapter


class FakeSettings:
    edi_aws_bucket_name = "test-bucket"
    enable_heavy_compute_queue = False


from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)

pytestmark = pytest.mark.asyncio


async def test_transform_edi_to_json_success() -> None:
    # Arrange
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()

    trace_id = "trace-123"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "edi_data": "ISA*00*...",
        "format_standard": "X12",
        "transaction_type": "850",
        "status": MessageStatus.RECEIVED,
    }

    # Act
    settings = FakeSettings()
    import typing

    from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

    uow_casted = typing.cast(DataPlaneUnitOfWorkPort, uow)
    from edi.config.settings import AppSettings

    settings_casted = typing.cast(AppSettings, settings)
    use_case = DispatchInboundTransformUseCase(
        uow=uow_casted, transformer=transformer, settings=settings_casted
    )
    await use_case.execute(trace_id)

    # Assert — outbox event was created instead of transformer being called
    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == PipelineEventType.COMPUTE_TRANSFORM_EVENT.value
    assert event["payload"]["trace_id"] == trace_id
    assert event["payload"]["direction"] == MessageDirection.INBOUND.value
    assert event["payload"]["standard"] == "X12"
    # UoW was committed
    assert uow.committed


async def test_transform_missing_message_raises_error() -> None:
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()

    settings = FakeSettings()
    import typing

    from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

    uow_casted = typing.cast(DataPlaneUnitOfWorkPort, uow)
    from edi.config.settings import AppSettings

    settings_casted = typing.cast(AppSettings, settings)
    use_case = DispatchInboundTransformUseCase(
        uow=uow_casted, transformer=transformer, settings=settings_casted
    )

    with pytest.raises(ValueError, match="No EDI message found for trace_id=invalid-trace"):
        await use_case.execute("invalid-trace")
