from io import StringIO

import pytest

from bots_core.domain.exceptions import InMessageError
from bots_core.domain.parsers.base import var
from bots_core.infrastructure.config.botsconfig import SFIELD, VALUE


class MockParser(var):
    def __init__(self, text):
        self.rawinput = text
        self._text_stream = StringIO(text)
        self.ta_info = {
            "frompartner": "mock",
            "record_sep": "'",
            "sfield_sep": ":",
            "field_sep": "+",
            "escape": "\\",
            "skip_char": "\r\n",
            "quote_char": '"',
            "charset": "utf-8",
            "record_tag_sep": "+",
            "reserve": "*",
            "strict_syntax_check": False,
            "strip_value": False,
        }
        self.lex_records = []
        self.errorlist = []
        self.errorfatal = True
        self.messagetypetxt = "MockParser "

    def do_lex(self):
        self._lex()


def test_parser_lexer_quoted_string():
    """Test the lexer handling quoted strings with spaces and escaped characters."""
    p = MockParser('SEG+"this is a quote: ""inner"" \\"escaped\\" "+FLDB\'')
    p.do_lex()
    values = [r[VALUE] for r in p.lex_records[0]]
    assert values == ["SEG", 'this is a quote: "inner" "escaped" ', "FLDB"]


def test_parser_lexer_escape_character_not_in_quote():
    """Test escape characters functioning outside of quoted strings."""
    p = MockParser("SEG+field\\+with\\'escaped+FLDB'")
    p.do_lex()
    values = [r[VALUE] for r in p.lex_records[0]]
    assert values == ["SEG", "field+with'escaped", "FLDB"]


def test_parser_lexer_multiple_skips():
    """Test that skipped characters (like \\r and \\n) are ignored."""
    p = MockParser("SEG\r\n+\r\nFLD1\r\n+\r\nFLD2\r\n'")
    p.do_lex()
    values = [r[VALUE] for r in p.lex_records[0]]
    assert values == ["SEG", "FLD1", "FLD2"]


def test_parser_lexer_consecutive_separators():
    """Test consecutive subfield and field separators."""
    p = MockParser("SEG++FLD1::+FLD2'")
    p.do_lex()
    # Expect: 'SEG', '', 'FLD1', '', '', 'FLD2'
    values = [r[VALUE] for r in p.lex_records[0]]
    sfields = [r[SFIELD] for r in p.lex_records[0]]
    assert values == ["SEG", "", "FLD1", "", "", "FLD2"]
    assert sfields == [0, 0, 0, 1, 1, 0]


def test_parser_lexer_trailing_separators():
    """Test trailing separators without data."""
    p = MockParser("SEG+FLD1++'")
    p.do_lex()
    values = [r[VALUE] for r in p.lex_records[0]]
    assert values == ["SEG", "FLD1", "", ""]


def test_separatorcheck_uniqueness():
    with pytest.raises(InMessageError, match=r"\[A64\]"):
        var.separatorcheck("++'")


def test_separatorcheck_space():
    with pytest.raises(InMessageError, match=r"\[A65\]"):
        var.separatorcheck("+ '")


def test_separatorcheck_alfanumeric():
    with pytest.raises(InMessageError, match=r"\[A66\]"):
        var.separatorcheck("+a'")


def test_parsefields_repeating_element_not_allowed():
    p = MockParser("SEG+FLD1*FLD2'")
    p.do_lex()

    from bots_core.domain.models import create_field_definition, create_structure_node

    struct = create_structure_node(
        {
            0: "SEG",
            1: 1,
            2: 1,
            6: [
                create_field_definition(["SEG", "M", 3, "AN", True, 0, 3, "AN", 1]),
                create_field_definition(["FLD1", "M", 4, "AN", True, 0, 4, "AN", 1]),
            ],
        }
    )

    p._parsefields(p.lex_records[0], struct)
    assert any("[F40]" in err for err in p.errorlist)
