from unittest.mock import AsyncMock, patch

import pytest
from pipeline.adapters.transformer import BotsTransformerAdapter
from transformer.domain.models import ParsedEdiPayload, TransactionSet

pytestmark = pytest.mark.asyncio


@patch("pipeline.adapters.transformer.BotsEDIAdapter.translate")
async def test_bots_transformer_edi_to_json(mock_translate: AsyncMock) -> None:
    mock_payload = ParsedEdiPayload(
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
    mock_translate.return_value = mock_payload

    adapter = BotsTransformerAdapter()
    result = await adapter.translate_edi_to_json(b"ISA*00*", "X12", "850")

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
    mock_translate.assert_awaited_once_with(b"ISA*00*")


async def test_bots_transformer_json_to_edi_success() -> None:
    from unittest.mock import patch

    adapter = BotsTransformerAdapter()

    with patch.object(adapter._adapter, "serialize_to_edi", return_value=("ISA*...~", [])):
        result = await adapter.translate_json_to_edi({"foo": "bar"}, "X12", "850", {})
        assert result == b"ISA*...~"
