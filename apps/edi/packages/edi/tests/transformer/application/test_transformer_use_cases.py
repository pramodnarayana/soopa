import pytest

from edi.adapters.outbound.transformer.application.use_cases import ProcessInboundEdiUseCase
from edi.adapters.outbound.transformer.domain.models import ParsedEdiPayload, TransactionSet


class FakeStoragePort:
    def __init__(self, raw_data: bytes):
        self.raw_data = raw_data
        self.called_with_uri: str | None = None

    async def get_raw_payload(self, s3_uri: str) -> bytes:
        self.called_with_uri = s3_uri
        return self.raw_data


class FakeTransformerPort:
    def __init__(self, expected_payload: ParsedEdiPayload):
        self.expected_payload = expected_payload
        self.called_with_raw_edi: bytes | None = None

    async def transform(self, raw_edi: bytes) -> ParsedEdiPayload:
        self.called_with_raw_edi = raw_edi
        return self.expected_payload


class FakeRepositoryPort:
    def __init__(self):
        self.saved_trace_id = None
        self.saved_payload = None

    async def save_parsed_payload(self, trace_id: str, payload: ParsedEdiPayload) -> None:
        self.saved_trace_id = trace_id
        self.saved_payload = payload


@pytest.mark.asyncio
async def test_process_inbound_edi_use_case_success():
    """
    Tests the pure orchestration logic of ProcessInboundEdiUseCase
    without using any mock frameworks, adhering to enterprise zero-mock standards.
    """
    raw_edi_fixture = b"ISA*00*..."
    expected_parsed_payload = ParsedEdiPayload(
        sender_id="SENDER123",
        receiver_id="RECEIVER456",
        interchange_control_number="000000001",
        transactions=[
            TransactionSet(transaction_type="850", control_number="0001", data={"po_number": "123"})
        ],
    )

    # Arrange: inject fake dependencies
    storage = FakeStoragePort(raw_data=raw_edi_fixture)
    transformer = FakeTransformerPort(expected_payload=expected_parsed_payload)
    repository = FakeRepositoryPort()

    use_case = ProcessInboundEdiUseCase(
        storage_port=storage, transformer_port=transformer, repository_port=repository
    )

    # Act
    trace_id = "trace-123"
    s3_uri = "s3://bucket/test.x12"
    result = await use_case.execute(trace_id, s3_uri)

    # Assert
    assert storage.called_with_uri == s3_uri
    assert transformer.called_with_raw_edi == raw_edi_fixture
    assert repository.saved_trace_id == trace_id
    assert repository.saved_payload == expected_parsed_payload
    assert result == expected_parsed_payload
