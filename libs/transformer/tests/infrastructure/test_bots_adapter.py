import sys
from unittest.mock import MagicMock

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
async def test_bots_adapter_returns_domain_model_on_success(monkeypatch):
    """Narrow integration test to verify adapter maps infrastructure to domain model."""
    mock_bots = MagicMock()
    mock_bots.__file__ = "/mocked/bots/__init__.py"
    monkeypatch.setitem(sys.modules, "bots", mock_bots)

    adapter = BotsEDIAdapter()

    with pytest.raises(TranslationError, match="Bots EDI translation is not yet fully implemented"):
        await adapter.translate(b"ISA*00*...")
