"""
test_exceptions.py — Tests for bots_core exception classes.
Covers the InMessageError, OutMessageError, BotsError hierarchy and formatting.
"""

import pytest

from bots_core.domain.exceptions import (
    BotsError,
    InMessageError,
    MappingFormatError,
    OutMessageError,
)


def test_inmessage_error_simple():
    err = InMessageError("Some error occurred")
    assert "Some error occurred" in str(err)


def test_inmessage_error_with_format_dict():
    err = InMessageError("Error %(code)s at %(pos)s", {"code": "A60", "pos": "3"})
    msg = str(err)
    assert "A60" in msg
    assert "3" in msg


def test_outmessage_error_simple():
    err = OutMessageError("Output error")
    assert "Output error" in str(err)


def test_outmessage_error_with_dict():
    err = OutMessageError("Field %(field)s too long", {"field": "ISA06"})
    msg = str(err)
    assert "ISA06" in msg


def test_mapping_format_error():
    err = MappingFormatError("Bad mpath %(mpath)s", {"mpath": "BOTSID"})
    assert "BOTSID" in str(err)


def test_error_hierarchy():
    err = InMessageError("x")
    assert isinstance(err, BotsError)
    assert isinstance(err, Exception)

    err2 = OutMessageError("y")
    assert isinstance(err2, BotsError)


def test_raise_and_catch_inmessage():
    with pytest.raises(InMessageError) as exc_info:
        raise InMessageError("Test raise %(val)s", {"val": "42"})
    assert "42" in str(exc_info.value)


def test_raise_and_catch_outmessage():
    with pytest.raises(OutMessageError) as exc_info:
        raise OutMessageError("Out raise %(x)s", {"x": "99"})
    assert "99" in str(exc_info.value)


def test_error_str_with_no_format():
    """Error with no format dict should still str() cleanly."""
    err = InMessageError("plain message")
    assert str(err) == "plain message"
