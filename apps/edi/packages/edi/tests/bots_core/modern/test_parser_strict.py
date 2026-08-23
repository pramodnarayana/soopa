"""
Tests for base parser (var class) covering strict_syntax_check branches
and allow_lastrecordnotclosedproperly behavior.
"""

from io import StringIO

import pytest

from edi.core.bots.config.botsconfig import SFIELD, VALUE
from edi.core.bots.domain.exceptions import InMessageError
from edi.core.bots.domain.parsers.base import var


class StrictParser(var):
    """Minimal concrete parser using strict_syntax_check=True."""

    def __init__(self, text, strict=True, allow_unclosed=False):
        self.rawinput = text
        self._text_stream = StringIO(text)
        self.ta_info = {
            "frompartner": "mock",
            "record_sep": "'",
            "sfield_sep": ":",
            "field_sep": "+",
            "escape": "?",
            "skip_char": "",
            "quote_char": "",
            "charset": "utf-8",
            "record_tag_sep": "",
            "reserve": "*",
            "strict_syntax_check": strict,
            "allow_lastrecordnotclosedproperly": allow_unclosed,
        }
        self.lex_records = []

    def do_lex(self):
        self._lex()


def test_strict_syntax_space_between_records():
    """strict mode: space characters between segments raises error."""
    p = StrictParser("REC+1'  REC+2'", strict=True)
    with pytest.raises(InMessageError, match="Found space characters between segments"):
        p.do_lex()


def test_non_strict_syntax_space_between_records_allowed():
    """non-strict mode: space between segments is silently ignored."""
    p = StrictParser("REC+1'  REC+2'", strict=False)
    p.do_lex()
    assert len(p.lex_records) == 2


def test_strict_double_record_separator():
    """strict mode: double record separator raises error."""
    p = StrictParser("REC+1''", strict=True)
    with pytest.raises(InMessageError, match="Found double record separator"):
        p.do_lex()


def test_non_strict_double_record_separator_kept():
    """non-strict mode: double separator creates empty record (current behavior)."""
    p = StrictParser("REC+1''", strict=False)
    p.do_lex()
    # first record is 'REC+1', second is empty
    assert len(p.lex_records) == 2


def test_allow_lastrecordnotclosedproperly():
    """allow_lastrecordnotclosedproperly: unclosed trailing record is kept."""
    p = StrictParser("REC+1", strict=False, allow_unclosed=True)
    p.do_lex()
    assert len(p.lex_records) == 1
    assert p.lex_records[0][0][VALUE] == "REC"


def test_lastrecord_not_closed_raises_by_default():
    """Default: trailing data without record sep raises InMessageError."""
    p = StrictParser("REC+1", strict=False, allow_unclosed=False)
    with pytest.raises(InMessageError, match="non-valid data at end of edi file"):
        p.do_lex()


def test_lexer_repeat_separator():
    """Repeat separator (reserve) marks field as SFIELD=2."""
    p = StrictParser("REC+A*B'", strict=False)
    p.do_lex()
    sfields = [f[SFIELD] for f in p.lex_records[0]]
    # REC(0), A(0), B(2)
    assert sfields == [0, 0, 2]
    assert p.lex_records[0][2][VALUE] == "B"


def test_lexer_subfield_separator():
    """Colon marks sub-field (SFIELD=1)."""
    p = StrictParser("REC+A:B+C'", strict=False)
    p.do_lex()
    sfields = [f[SFIELD] for f in p.lex_records[0]]
    values = [f[VALUE] for f in p.lex_records[0]]
    assert sfields == [0, 0, 1, 0]
    assert values == ["REC", "A", "B", "C"]


def test_lexer_escape_in_non_quoted_mode():
    """Escape character prevents the next char from being treated as separator."""
    p = StrictParser("REC+A?+B'", strict=False)
    p.do_lex()
    values = [f[VALUE] for f in p.lex_records[0]]
    assert values == ["REC", "A+B"]


def test_leftover_null_bytes_ignored():
    """Trailing \\x00 and \\x1a bytes after last record are silently discarded."""
    p = StrictParser("REC+1'\x00\x1a", strict=False)
    p.do_lex()
    assert len(p.lex_records) == 1
