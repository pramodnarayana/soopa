import pytest

from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.adapters.outbound.transformer.domain.models import ParsedEdiPayload, TransactionSet

pytestmark = pytest.mark.asyncio


class FakeBotsEDIAdapter:
    async def transform(self, payload: bytes) -> ParsedEdiPayload:
        return ParsedEdiPayload(
            sender_id="A",
            receiver_id="B",
            interchange_control_number="1",
            transactions=[
                TransactionSet(
                    transaction_type="850",
                    control_number="1",
                    gs_sender_id="GS_SENDER",
                    gs_receiver_id="GS_RECEIVER",
                    data={"foo": "bar"},
                )
            ],
        )

    def serialize_to_edi(self, ast: dict, standard: str) -> tuple[str, list[str]]:
        return "ISA*...~", []


async def test_bots_transformer_edi_to_json() -> None:
    fake_adapter = FakeBotsEDIAdapter()
    adapter = BotsTransformerAdapter(adapter=fake_adapter)

    result = await adapter.transform_edi_to_json(b"ISA*00*", "X12", "850")

    assert result is not None
    assert len(result) == 1
    txn = result[0]
    assert txn.transaction_type == "850"
    assert txn.isa_sender_id == "A"
    assert txn.isa_receiver_id == "B"
    assert txn.gs_sender_id == "GS_SENDER"
    assert txn.gs_receiver_id == "GS_RECEIVER"
    assert txn.control_number == "1"
    assert txn.payload == {"foo": "bar"}


async def test_bots_transformer_json_to_edi_success() -> None:
    fake_adapter = FakeBotsEDIAdapter()
    adapter = BotsTransformerAdapter(adapter=fake_adapter)

    result = await adapter.transform_json_to_edi({"foo": "bar"}, "X12", "850", {})
    assert result == b"ISA*...~"
