from typing import Any

import pytest

from edi.core.bots.utils.botslib import botsglobal


@pytest.fixture
def patch_data_dir(tmp_path) -> "Any":
    """
    Patches botsglobal.ini.get to return a temporary directory for data operations,
    and delegates all other lookups to the original getter.
    """
    orig_get = botsglobal.ini.get

    def patched_get(section, key, fallback="") -> "Any":
        if section == "directories" and key == "data":
            return str(tmp_path)
        return orig_get(section, key, fallback)

    botsglobal.ini.get = patched_get
    try:
        yield tmp_path
    finally:
        botsglobal.ini.get = orig_get
