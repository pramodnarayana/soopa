import codecs

import pytest
from bots_core.domain.inmessage import InMessageError
from bots_core.domain.node import Node
from bots_core.domain.parsers.edifact import edifact


def edifact_charset_search(encoding):
    if encoding in ["UNOA", "UNOB", "unoa", "unob"]:
        return codecs.lookup("ascii")
    return None


codecs.register(edifact_charset_search)


class MockGrammar:
    def __init__(self):
        self.syntax = {
            "decimaal": ".",
            "charset": "utf-8",
            "reserve": "",
            "envelope": "",
            "merge": False,
            "charset_dict": {"UNOA": "ascii", "UNOB": "ascii"},
            "forcequote": 1,
            "quote_char": '"',
            "field_sep": "+",
            "sfield_sep": ":",
            "record_sep": "'",
            "escape": "?",
            "record_tag_sep": "",
            "skip_char": "",
            "checkcharsetin": "strict",
        }


def test_edifact_sniff_una():
    syntax = MockGrammar().syntax.copy()
    parser = edifact(syntax)
    parser.defmessage = MockGrammar()

    # Valid UNA
    parser.rawinput = b"UNA:+.? 'UNB+UNOA:1+SENDER+RECEIVER+100101:1001+1'"
    parser._sniff()
    assert parser.ta_info["sfield_sep"] == ":"
    assert parser.ta_info["field_sep"] == "+"
    assert parser.ta_info["decimaal"] == "."
    assert parser.ta_info["escape"] == "?"
    assert parser.ta_info["reserve"] == ""
    assert parser.ta_info["record_sep"] == "'"


def test_edifact_sniff_unb_standard():
    syntax = MockGrammar().syntax.copy()
    parser = edifact(syntax)
    parser.defmessage = MockGrammar()

    # UNB UNOA
    parser.rawinput = b"UNB+UNOA:1+SENDER+RECEIVER+100101:1001+1'"
    parser._sniff()
    assert parser.ta_info["sfield_sep"] == ":"


def test_edifact_sniff_unb_unob():
    syntax = MockGrammar().syntax.copy()
    parser = edifact(syntax)
    parser.defmessage = MockGrammar()

    # UNB UNOB separators
    parser.rawinput = b"UNB\x1dUNOB\x1f1\x1dSENDER\x1dRECEIVER\x1d100101\x1f1001\x1d1\x1c"
    parser._sniff()
    assert parser.ta_info["sfield_sep"] == "\x1f"
    assert parser.ta_info["field_sep"] == "\x1d"


def test_edifact_sniff_invalid_unb():
    syntax = MockGrammar().syntax.copy()
    parser = edifact(syntax)
    parser.defmessage = MockGrammar()

    parser.rawinput = b"UNB*UNOA-1*SENDER*RECEIVER*100101-1001*1!"
    with pytest.raises(InMessageError, match="non-standard separators.+UNA segment is required"):
        parser._sniff()


def test_edifact_checkenvelope():
    syntax = MockGrammar().syntax.copy()
    parser = edifact(syntax)
    parser.defmessage = MockGrammar()
    parser.errorlist = []
    parser.messagetypetxt = "Test "

    root = Node()
    unb = Node({"BOTSID": "UNB", "0020": "UNB1"})
    unz = Node({"BOTSID": "UNZ", "0020": "UNZ1", "0036": "2"})

    unh1 = Node({"BOTSID": "UNH", "0062": "UNH1"})
    unt1 = Node({"BOTSID": "UNT", "0062": "UNT1", "0074": "2"})
    unh1.append(unt1)

    unh2 = Node({"BOTSID": "UNH", "0062": "UNH2"})
    unt2 = Node({"BOTSID": "UNT", "0062": "UNH2", "0074": "invalid"})
    unh2.append(unt2)

    unb.append(unh1)
    unb.append(unh2)
    unb.append(unz)
    root.append(unb)

    parser.root = root
    parser.checkenvelope()

    # UNB1 != UNZ1
    # UNH1 != UNT1
    # UNH2 unt count invalid
    # UNB count != 2 (it's 2)
    assert len(parser.errorlist) > 0
    assert any("UNB-reference" in err for err in parser.errorlist)
    assert any("UNH-reference" in err for err in parser.errorlist)
    assert any("invalid" in err for err in parser.errorlist)


def test_edifact_checkenvelope_with_ung():
    syntax = MockGrammar().syntax.copy()
    parser = edifact(syntax)
    parser.defmessage = MockGrammar()
    parser.errorlist = []
    parser.messagetypetxt = "Test "

    root = Node()
    unb = Node({"BOTSID": "UNB", "0020": "UNB1"})

    ung = Node({"BOTSID": "UNG", "0048": "UNG1"})
    une = Node({"BOTSID": "UNE", "0048": "UNE1", "0060": "invalid"})

    unh = Node({"BOTSID": "UNH", "0062": "UNH1"})
    unt = Node({"BOTSID": "UNT", "0062": "UNH1", "0074": "2"})
    unh.append(unt)

    ung.append(unh)
    ung.append(une)
    unb.append(ung)

    unz = Node({"BOTSID": "UNZ", "0020": "UNB1", "0036": "1"})
    unb.append(unz)
    root.append(unb)

    parser.root = root
    parser.checkenvelope()

    assert len(parser.errorlist) > 0
    assert any("UNG-reference" in err for err in parser.errorlist)
    assert any("Groupcount" in err for err in parser.errorlist)
