import contextlib
import uuid

import pytest
from seedwork.domain.exceptions import ErrorCode

from edi.application.use_cases.pipeline.compute_transform_use_case import (
    ComputeTransformCommand,
    ComputeTransformUseCase,
)
from edi.domain.enums import EdiDirection, MessageStatus
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.ports.outbound.transformer_port import ParsedEdiMessage, TransformerPort
from edi.testing.fakes.pipeline_fakes import (
    FakeDataPlaneUnitOfWork,
    FakeOutboxPublisher,
    InMemoryRepositoryAdapter,
)


class ErrorTransformer(TransformerPort):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def transform_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[ParsedEdiMessage]:
        raise self._exc

    async def transform_json_to_edi(self, *args: object, **kwargs: object) -> bytes:
        return b""


class FailingRepositoryAdapter(InMemoryRepositoryAdapter):
    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessageDomainModel | None:
        raise ValueError("Corrupt internal state")


@pytest.mark.asyncio
async def test_transformer_value_error_is_classified_as_terminal() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = str(uuid.uuid4())
    tenant_id = "tenant-test"

    msg = EdiMessageDomainModel(
        id="msg-err-1",
        trace_id=trace_id,
        tenant_id=tenant_id,
        direction=EdiDirection.INBOUND,
        edi_data="ISA*00*test~",
        status=MessageStatus.RECEIVED,
    )
    await uow.transactions.save(msg)

    @contextlib.asynccontextmanager
    async def uow_factory():
        yield uow

    transformer = ErrorTransformer(ValueError("Invalid syntax in segment GS"))
    publisher = FakeOutboxPublisher()

    use_case = ComputeTransformUseCase(
        transformer=transformer,
        uow_factory=uow_factory,
        publisher=publisher,
    )

    command = ComputeTransformCommand(
        trace_id=trace_id,
        tenant_id=tenant_id,
        idempotency_key="idemp-err-1",
    )

    await use_case.execute(command)

    # Verify message was permanently marked as transform failed
    updated_msg = await uow.transactions.get_edi_message(trace_id)
    assert updated_msg is not None
    assert updated_msg.status == MessageStatus.FAILED
    assert updated_msg.error_code == ErrorCode.TRANSFORMATION_FAILED


@pytest.mark.asyncio
async def test_repository_value_error_bubbles_as_transient() -> None:
    failing_repo = FailingRepositoryAdapter()
    uow = FakeDataPlaneUnitOfWork(repository=failing_repo)
    trace_id = "trace-err-2"
    tenant_id = "tenant-test"

    @contextlib.asynccontextmanager
    async def uow_factory():
        yield uow

    transformer = ErrorTransformer(ValueError("Should not be called"))
    publisher = FakeOutboxPublisher()

    use_case = ComputeTransformUseCase(
        transformer=transformer,
        uow_factory=uow_factory,
        publisher=publisher,
    )

    command = ComputeTransformCommand(
        trace_id=trace_id,
        tenant_id=tenant_id,
        idempotency_key="idemp-err-2",
    )

    with pytest.raises(ValueError, match="Corrupt internal state"):
        await use_case.execute(command)
