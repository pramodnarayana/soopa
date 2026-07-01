"""
test_botslib.py — Tests for bots_core utility functions.
Covers opendata, readdata, dirshouldbethere, formatting helpers, and error path utilities.
"""

import os

from bots_core.utils import botslib
from bots_core.utils.botslib import (
    dirshouldbethere,
    opendata,
    readdata,
)

# ---------------------------------------------------------------------------
# dirshouldbethere
# ---------------------------------------------------------------------------


def test_dirshouldbethere_creates_dir(patch_data_dir):
    new_dir = str(patch_data_dir / "subdir" / "nested")
    assert not os.path.exists(new_dir)
    assert dirshouldbethere(new_dir) is True
    assert os.path.isdir(new_dir)


def test_dirshouldbethere_existing_dir_is_noop(patch_data_dir):
    existing_dir = str(patch_data_dir)
    assert dirshouldbethere(existing_dir) is False  # Should not raise and return False
    assert os.path.isdir(existing_dir)


# ---------------------------------------------------------------------------
# opendata / readdata
# ---------------------------------------------------------------------------


def test_opendata_write_and_read(patch_data_dir):
    """Round-trip: write a file via opendata, read it back."""
    filename = "test_opendata.txt"
    content = "Hello, bots!\nLine two.\n"

    # Patch botsglobal so abspathdata resolves under patch_data_dir
    data_dir = str(patch_data_dir)

    original_get = botslib.botsglobal.ini.get

    def patched_get(section, key, fallback=""):
        if section == "directories" and key == "data":
            return data_dir
        return original_get(section, key, fallback)

    botslib.botsglobal.ini.get = patched_get  # type: ignore[method-assign]

    with opendata(filename, "w", charset="utf-8") as f:
        f.write(content)

    result = readdata(filename, charset="utf-8")
    assert result == content


def test_opendata_binary_write_and_read(patch_data_dir):
    """Write binary data and read it back via opendata_bin."""
    from bots_core.utils.botslib import opendata_bin

    filepath = str(patch_data_dir / "test_binary.edi")
    content = b"ISA*00*TEST~"

    original_get = botslib.botsglobal.ini.get

    def patched_get(section, key, fallback=""):
        if section == "directories" and key == "data":
            return str(patch_data_dir)
        return original_get(section, key, fallback)

    botslib.botsglobal.ini.get = patched_get  # type: ignore[method-assign]
    with opendata_bin(filepath, "wb") as f:
        f.write(content)

    with opendata_bin(filepath, "rb") as f:
        result = f.read()
    assert result == content


# ---------------------------------------------------------------------------
# get_relevant_text_for_UnicodeError
# ---------------------------------------------------------------------------


def test_get_relevant_text_for_unicode_error():
    """UnicodeError helper returns the relevant bytes slice around the error."""
    try:
        b"\xff".decode("utf-8")
    except UnicodeDecodeError as exc:
        result = botslib.get_relevant_text_for_UnicodeError(exc)
    # Returns a bytes slice
    assert isinstance(result, bytes)
    assert b"\xff" in result
