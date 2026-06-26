import pytest
from unittest.mock import patch, MagicMock
from bots_core.infrastructure.config import botsinit
from bots_core.infrastructure.config.context import BotsContext, set_context

def test_botsinit_generalinit_sets_correct_paths():
    """
    Verify that the legacy configuration initializer successfully parses
    directory structures and populates the isolated BotsContext.
    """
    ctx = BotsContext()
    set_context(ctx)

    with patch("os.path.abspath", return_value="/mocked/path"), \
         patch("bots_core.utils.botslib.botsbaseimport") as mock_import, \
         patch("bots_core.infrastructure.config.botsinit.BotsConfig") as mock_config_cls:

        mock_import.return_value.__path__ = ["/mocked/path"]

        mock_ini = MagicMock()
        mock_config_cls.return_value = mock_ini
        mock_ini.get.return_value = "mocked_value"

        # Run initialization
        botsinit.generalinit("/mocked/config/dir")

        # Verify context was updated correctly
        assert ctx.configdir == "/mocked/config/dir"
        assert ctx.ini is not None

        # Verify it explicitly fetched directories
        mock_ini.get.assert_any_call("directories", "usersys", "usersys")
