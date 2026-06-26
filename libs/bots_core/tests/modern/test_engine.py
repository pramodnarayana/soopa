import pytest
from unittest.mock import patch, MagicMock
from bots_core.application.use_cases import engine
from bots_core.infrastructure.config.context import BotsContext, set_context
from bots_core.infrastructure.config import botsglobal

def test_engine_minta4query_execution():
    """
    Verify that the core engine use case executes successfully, safely
    fetches configuration from the isolated proxy, and delegates correctly.
    """
    ctx = BotsContext()
    set_context(ctx)

    mock_ini = MagicMock()
    mock_ini.get.return_value = "report"
    mock_ini.getboolean.return_value = False

    mock_logger = MagicMock()
    mock_db = MagicMock()

    mock_current_run = MagicMock()
    mock_current_run.minta4query = 12345

    ctx.ini = mock_ini
    ctx.logger = mock_logger
    ctx.db_port = mock_db
    ctx.currentrun = mock_current_run

    with patch("bots_core.utils.botslib.botsinfo_display", return_value="System Info"), \
         patch("bots_core.utils.botslib.query", return_value=[]), \
         patch("bots_core.infrastructure.config.botsinit.generalinit"), \
         patch("bots_core.infrastructure.config.botsinit.initenginelogging", return_value=mock_logger), \
         patch("bots_core.utils.botslib.tryrunscript"), \
         patch("bots_core.utils.botslib.botsimport", return_value=(None, None)), \
         patch("bots_core.application.use_cases.router.rundispatcher", return_value=0) as mock_router_run, \
         patch("os.chdir"), \
         patch("sys.exit"):

        # We manually inject the dependencies since the actual Django engine is removed
        # and botsglobal acts as the proxy
        engine.start()

        # Ensure it routed correctly
        mock_router_run.assert_called_once()

        # Ensure it didn't leak or crash
        assert botsglobal.currentrun.minta4query == 12345
