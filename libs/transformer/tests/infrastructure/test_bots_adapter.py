import pytest
from transformer.domain.exceptions import TranslationError
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter


@pytest.mark.asyncio
async def test_bots_adapter_raises_translation_error_on_empty_payload():
    """Narrow integration test to verify adapter handles failure scenarios."""
    adapter = BotsEDIAdapter()

    with pytest.raises(TranslationError, match="Payload is completely empty"):
        await adapter.translate(b"")


@pytest.mark.asyncio
async def test_bots_adapter_returns_domain_model_on_success():
    """Narrow integration test to verify adapter maps infrastructure to domain model."""
    adapter = BotsEDIAdapter()

    # Passing a fake payload
    result = await adapter.translate(b"ISA*00*...")

    # Validate the infrastructure layer successfully constructed the pure domain model
    assert result.sender_id == "BOTS-ADAPTER-STUB"
    assert result.receiver_id == "NEXIOM"
    assert result.interchange_control_number == "0001"
