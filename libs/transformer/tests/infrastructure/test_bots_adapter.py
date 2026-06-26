import sys
from unittest.mock import MagicMock, patch

import pytest
from transformer.domain.exceptions import TranslationError
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter


@pytest.mark.asyncio
@patch("transformer.infrastructure.adapters.bots_adapter.botsinit")
async def test_bots_adapter_raises_translation_error_on_empty_payload(mock_botsinit):
    """Narrow integration test to verify adapter handles failure scenarios."""
    mock_session = MagicMock()
    adapter = BotsEDIAdapter(config_dir="/tmp", session=mock_session)

    with pytest.raises(TranslationError, match="Payload is completely empty"):
        await adapter.translate(b"")


@pytest.mark.asyncio
@patch("transformer.infrastructure.adapters.bots_adapter.botsinit")
async def test_bots_adapter_returns_domain_model_on_success(mock_botsinit, monkeypatch):
    """Narrow integration test to verify adapter maps infrastructure to domain model."""
    mock_bots = MagicMock()
    mock_bots.__file__ = "/mocked/bots_core/__init__.py"
    monkeypatch.setitem(sys.modules, "bots_core", mock_bots)

    mock_session = MagicMock()
    adapter = BotsEDIAdapter(config_dir="/tmp", session=mock_session)

    with pytest.raises(TranslationError, match="Bots EDI translation is not yet fully implemented"):
        await adapter.translate(b"ISA*00*...")
