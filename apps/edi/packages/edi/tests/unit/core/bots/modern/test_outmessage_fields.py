"""
test_outmessage_advanced.py
Tests for bots_core.domain.outmessage covering advanced features like repeating fields, repeating composites, and number formatting.
"""

from edi.core.bots.config.botsconfig import (
    VALUE,
)
from edi.core.bots.domain.node import Node
from edi.core.bots.domain.outmessage import Outmessage


class MockGrammar:
    def __init__(self):
        self.syntax = {
            "decimaal": ".",
            "charset": "utf-8",
            "reserve": "",
            "envelope": "",
            "merge": False,
            "charset_dict": {},
        }

        # Structure format: ID(0), MIN(1), MAX(2), ... FIELDS(6)
        self.structure = [["REC1", 0, 99, 0, 0, ["REC1"], None]]
        self.recorddefs = {
            "REC1": [
                [
                    "REC1",  # 0 ID
                    "M",  # 1 MANDATORY
                    3,  # 2 LENGTH
                    "AN",  # 3 FORMAT
                    True,  # 4 ISFIELD
                    0,  # 5 DECIMALS
                    3,  # 6 MINLENGTH
                    "AN",  # 7 BFORMAT
                    1,  # 8 MAXREPEAT
                ],
                [
                    "REP_FIELD",
                    "C",
                    10,
                    "AN",
                    True,
                    0,  # DECIMALS
                    0,  # MINLENGTH
                    "AN",
                    5,  # MAXREPEAT
                ],
                [
                    "REP_COMP",
                    "C",
                    [
                        ["SUB1", "C", 5, "AN", True, 0, 0, "AN", 1],
                        ["SUB2", "C", 5, "AN", True, 0, 0, "AN", 1],
                    ],
                    "AN",
                    False,  # ISFIELD is False for composite
                    0,  # DECIMALS
                    0,  # MINLENGTH
                    "AN",
                    5,  # MAXREPEAT
                ],
                [
                    "NUM_FLD",
                    "C",
                    10,
                    "NL",  # Numeric left aligned
                    True,
                    2,  # DECIMALS
                    5,  # MINLENGTH
                    "N",
                    1,  # MAXREPEAT
                ],
                [
                    "NUM_FLD_NR",
                    "C",
                    10,
                    "NR",  # Numeric right aligned
                    True,
                    2,  # DECIMALS
                    5,  # MINLENGTH
                    "N",
                    1,  # MAXREPEAT
                ],
                [
                    "NUM_FLD_NZ",
                    "C",
                    10,
                    "R",  # Numeric zero padded
                    True,
                    2,  # DECIMALS
                    5,  # MINLENGTH
                    "N",
                    1,  # MAXREPEAT
                ],
            ]
        }
        from edi.core.bots.domain.models import (
            create_field_definition,
            create_structure_node,
        )

        self.recorddefs["REC1"] = [create_field_definition(f) for f in self.recorddefs["REC1"]]
        self.structure[0][6] = self.recorddefs["REC1"]
        self.structure = [create_structure_node({i: v for i, v in enumerate(self.structure[0])})]


class MockOutmessage(Outmessage):
    def __init__(self, ta_info):
        self.ta_info = ta_info
        self.errorlist = []
        self.messagetypetxt = "MockMessage "
        self.lex_records = []
        self.defmessage = MockGrammar()
        self.root = Node()


def test_outmessage_repeating_field():
    ta_info = {"lengthnumericbare": False, "decimaal": ".", "stripfield_sep": True}
    msg = MockOutmessage(ta_info)

    node = Node(record={"REC1": "REC", "REP_FIELD": ["val1", "val2"]})

    msg._tree2recordfields(node.record, msg.defmessage.structure[0])

    # lex_records should contain a list of fields/repeats
    assert len(msg.lex_records) == 1
    # Find REP_FIELD representations
    rep_field_vals = [f[VALUE] for f in msg.lex_records[0] if f.get(VALUE) in ("val1", "val2")]
    assert len(rep_field_vals) == 2


def test_outmessage_repeating_composite():
    ta_info = {"lengthnumericbare": False, "decimaal": ".", "stripfield_sep": True}
    msg = MockOutmessage(ta_info)

    node = Node(
        record={
            "REC1": "REC",
            "REP_COMP": [
                {"SUB1": "a1", "SUB2": "b1"},
                {"SUB1": "a2", "SUB2": "b2"},
                {},  # Empty composite test
            ],
        }
    )

    msg._tree2recordfields(node.record, msg.defmessage.structure[0])

    assert len(msg.lex_records) == 1
    vals = [f[VALUE] for f in msg.lex_records[0] if f.get(VALUE)]
    assert "a1" in vals
    assert "b1" in vals
    assert "a2" in vals
    assert "b2" in vals


def test_outmessage_format_numeric_left():
    ta_info = {"lengthnumericbare": False, "decimaal": ".", "stripfield_sep": True}
    msg = MockOutmessage(ta_info)

    field_def = msg.defmessage.recorddefs["REC1"][3]  # NUM_FLD, NL, MINLENGTH 5, DECIMALS 2
    value = "1.2"
    from edi.core.bots.domain.models import StructureNode

    struct = StructureNode(id="REC1", min_occ=1, max_occ=1, mpath=["REC1"])

    formatted = msg._formatfield(value, field_def, struct, node_instance=Node())

    assert formatted == "1.20 "


def test_outmessage_format_numeric_right():
    ta_info = {"lengthnumericbare": True, "decimaal": ".", "stripfield_sep": True}
    msg = MockOutmessage(ta_info)

    field_def = msg.defmessage.recorddefs["REC1"][4]  # NUM_FLD_NR, NR, MINLENGTH 5, DECIMALS 2
    value = "-1.2"
    from edi.core.bots.domain.models import StructureNode

    struct = StructureNode(id="REC1", min_occ=1, max_occ=1, mpath=["REC1"])

    # lengthnumericbare=True adds lengthcorrection for '-' and '.'
    formatted = msg._formatfield(value, field_def, struct, node_instance=Node())

    assert formatted == "  -1.20"


def test_outmessage_format_numeric_zfill():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ",",
        "json_write_numericals": False,
        "stripfield_sep": True,
    }
    msg = MockOutmessage(ta_info)

    field_def = msg.defmessage.recorddefs["REC1"][5]  # NUM_FLD_NZ, R, MINLENGTH 5, DECIMALS 2
    value = "1.2"
    from edi.core.bots.domain.models import StructureNode

    struct = StructureNode(id="REC1", min_occ=1, max_occ=1, mpath=["REC1"])

    formatted = msg._formatfield(value, field_def, struct, node_instance=Node())

    assert formatted == "01,20"


def test_outmessage_format_numeric_invalid():
    ta_info = {"lengthnumericbare": False, "decimaal": ".", "stripfield_sep": True}
    msg = MockOutmessage(ta_info)

    field_def = msg.defmessage.recorddefs["REC1"][3]
    value = "abc"
    from edi.core.bots.domain.models import StructureNode

    struct = StructureNode(id="REC1", min_occ=1, max_occ=1, mpath=["REC1"])

    formatted = msg._formatfield(value, field_def, struct, node_instance=Node())
    assert "abc" in formatted
    assert len(msg.errorlist) == 1
    assert "numerical format not valid" in msg.errorlist[0]
