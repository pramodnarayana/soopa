import pytest

from bots_core.domain.exceptions import OutMessageError
from bots_core.domain.models import create_field_definition, create_structure_node
from bots_core.domain.node import Node
from bots_core.domain.outmessage import Outmessage
from bots_core.infrastructure.config.botsconfig import FORMATFROMGRAMMAR, SFIELD, VALUE


class MockGrammar:
    def __init__(self):
        self.grammarname = "mockgrammar"
        self.syntax = {
            "decimaal": ".",
            "charset": "utf-8",
            "reserve": "",
            "envelope": "",
            "merge": False,
            "charset_dict": {},
            "forcequote": 1,
            "quote_char": '"',
            "field_sep": "+",
            "record_sep": "'",
        }
        self.structure = [
            create_structure_node(
                {
                    0: "REC1",
                    1: 0,
                    2: 9,
                    3: 0,
                    4: 0,
                    6: [
                        create_field_definition(["REC1", "M", 3, "AN", True, 0, 3, "AN", 1]),
                        create_field_definition(["NUM1", "C", 5, "N", True, 2, 5, "N", 1]),
                        create_field_definition(["FLOAT1", "C", 5, "R", True, 0, 5, "R", 1]),
                        create_field_definition(["IMP1", "C", 5, "I", True, 0, 5, "I", 1]),
                    ],
                }
            )
        ]
        self.recorddefs = {"REC1": self.structure[0].fields}


class MockOutmessage(Outmessage):
    def __init__(self, ta_info=None):
        if ta_info is None:
            ta_info = {
                "editype": "csv",
                "messagetype": "mock",
                "lengthnumericbare": False,
                "decimaal": ".",
                "charset": "utf-8",
                "checkcharsetout": "strict",
                "has_structure": True,
                "checkunknownentities": False,
            }
        self.ta_info = ta_info
        self.errorlist = []
        self.root = Node()
        self.defmessage = MockGrammar()
        self.ta_info.update(self.defmessage.syntax)
        self.lex_records = []
        self.messagetypetxt = "Mock: "
        self.errorfatal = True

    def messagegrammarread(self, typeofgrammarfile):
        pass


def test_outmessage_write_empty_root_no_children():
    out = MockOutmessage()
    out.root.record = None
    with pytest.raises(OutMessageError, match="No outgoing message"):
        out.writeall()


def test_outmessage_format_default_value_numeric():
    out = MockOutmessage()
    # Test lines 741-762 default numerics
    field_def_N = create_field_definition(["NUM", "M", 5, "N", True, 2, 5, "N", 1])
    assert out._initfield(field_def_N) == "00.00"

    field_def_R = create_field_definition(["FLOAT", "M", 5, "R", True, 0, 5, "R", 1])
    assert out._initfield(field_def_R) == "00000"

    field_def_I = create_field_definition(["IMP", "M", 5, "I", True, 0, 5, "I", 1])
    assert out._initfield(field_def_I) == "00000"

    field_def_A = create_field_definition(["STR", "M", 5, "AN", True, 0, 5, "A", 1])
    assert out._initfield(field_def_A) == ""


def test_outmessage_record2string_forcequote():
    out = MockOutmessage()
    out.ta_info["forcequote"] = 2  # Quote only strings
    out.ta_info["quote_char"] = '"'
    out.ta_info["field_sep"] = "+"
    out.ta_info["sfield_sep"] = ":"
    out.ta_info["record_sep"] = "'"
    out.ta_info["escape"] = "\\"
    out.ta_info["record_tag_sep"] = "+"
    out.ta_info["add_crlfafterrecord_sep"] = ""

    # lex_records is list of records. Each record is list of dicts.
    lex_records = [
        [
            {VALUE: "REC1", SFIELD: 0, FORMATFROMGRAMMAR: "AN"},
            {VALUE: "123", SFIELD: 0, FORMATFROMGRAMMAR: "N"},
        ]
    ]

    res = out.record2string(lex_records)
    assert res == '"REC1"+123\''


def test_outmessage_record2string_quote_when_sep_present():
    out = MockOutmessage()
    out.ta_info["forcequote"] = 0  # No force quote
    out.ta_info["quote_char"] = '"'
    out.ta_info["field_sep"] = "+"
    out.ta_info["sfield_sep"] = ":"
    out.ta_info["record_sep"] = "'"
    out.ta_info["escape"] = "\\"
    out.ta_info["record_tag_sep"] = "+"
    out.ta_info["add_crlfafterrecord_sep"] = ""

    lex_records = [
        [
            {VALUE: "REC+1", SFIELD: 0, FORMATFROMGRAMMAR: "AN"},
            {VALUE: "REC'2", SFIELD: 0, FORMATFROMGRAMMAR: "AN"},
            {VALUE: 'REC"3', SFIELD: 0, FORMATFROMGRAMMAR: "AN"},
        ]
    ]

    res = out.record2string(lex_records)
    assert res == '"REC+1"+"REC\'2"+"REC""3"\''


def test_outmessage_replacechar():
    # Simulate x12 subclass
    class x12(MockOutmessage):
        def _getescapechars(self):
            return (
                self.ta_info["field_sep"] + self.ta_info["record_sep"] + self.ta_info["sfield_sep"]
            )

    out = x12()
    out.ta_info["quote_char"] = ""
    out.ta_info["field_sep"] = "+"
    out.ta_info["sfield_sep"] = ":"
    out.ta_info["record_sep"] = "'"
    out.ta_info["escape"] = ""
    out.ta_info["record_tag_sep"] = ""
    out.ta_info["add_crlfafterrecord_sep"] = ""
    out.ta_info["replacechar"] = ""

    lex_records = [[{VALUE: "REC+1", SFIELD: 0, FORMATFROMGRAMMAR: "AN"}]]

    with pytest.raises(OutMessageError, match="used as separator in this x12 file"):
        out.record2string(lex_records)

    out.ta_info["replacechar"] = "_"
    res = out.record2string(lex_records)
    assert res == "REC_1'"


def test_outmessage_escape_non_x12():
    class EdifactMock(MockOutmessage):
        def _getescapechars(self):
            return (
                self.ta_info["field_sep"]
                + self.ta_info["record_sep"]
                + self.ta_info["sfield_sep"]
                + self.ta_info["escape"]
            )

    out = EdifactMock()
    out.ta_info["quote_char"] = ""
    out.ta_info["field_sep"] = "+"
    out.ta_info["sfield_sep"] = ":"
    out.ta_info["record_sep"] = "'"
    out.ta_info["escape"] = "?"
    out.ta_info["record_tag_sep"] = ""
    out.ta_info["add_crlfafterrecord_sep"] = ""
    out.ta_info["replacechar"] = ""

    lex_records = [[{VALUE: "REC+1", SFIELD: 0, FORMATFROMGRAMMAR: "AN"}]]

    res = out.record2string(lex_records)
    assert res == "REC?+1'"
