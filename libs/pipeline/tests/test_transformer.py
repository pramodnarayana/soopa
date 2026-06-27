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
            TransactionSet(transaction_type="850", control_number="1", data={"foo": "bar"})
        ],
    )
    mock_translate.return_value = mock_payload

    adapter = BotsTransformerAdapter()
    result = await adapter.translate_edi_to_json(b"ISA*00*", "X12", "850")

    assert result == {"foo": "bar"}
    mock_translate.assert_awaited_once_with(b"ISA*00*")


async def test_bots_transformer_json_to_edi() -> None:
    # No mock needed since it returns a hardcoded string currently
    adapter = BotsTransformerAdapter()
    result = await adapter.translate_json_to_edi({"foo": "bar"}, "X12", "850")

    assert result == b"ST*850*0001~SE*2*0001~"
