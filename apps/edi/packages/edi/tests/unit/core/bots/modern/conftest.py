import pytest

from edi.core.bots.utils.botslib import botsglobal


@pytest.fixture
def patch_data_dir(tmp_path) -> str:
    """
    Replaces botsglobal.ini.get to return a temporary directory for data operations,
    and delegates all other lookups to the original getter, avoiding unittest.mock.
    """
    orig_get = botsglobal.ini.get

    def patched_get(section: str, key: str, fallback: str = "") -> str:
        if section == "directories" and key == "data":
            return str(tmp_path)
        return orig_get(section, key, fallback)

    botsglobal.ini.get = staticmethod(patched_get)
    try:
        yield tmp_path
    finally:
        botsglobal.ini.get = staticmethod(orig_get)
