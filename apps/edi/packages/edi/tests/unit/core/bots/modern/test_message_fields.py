"""
test_message_advanced.py
Advanced tests for message.py checking edge cases in repeating fields, max repeats, and formatting.
"""

import pytest

from edi.core.bots.domain.exceptions import MappingFormatError
from edi.core.bots.domain.message import Message
from edi.core.bots.domain.node import Node


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
        }

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
                    "M",
                    10,
                    "AN",
                    True,
                    0,  # DECIMALS
                    0,  # MINLENGTH
                    "AN",
                    2,  # MAXREPEAT
                ],
                [
                    "REP_COMP",
                    "M",
                    [
                        ["SUB1", "M", 5, "AN", True, 0, 0, "AN", 1],
                        ["SUB2", "C", 5, "AN", True, 0, 0, "AN", 1],
                    ],
                    "AN",
                    False,  # ISFIELD is False for composite
                    0,  # DECIMALS
                    0,  # MINLENGTH
                    "AN",
                    2,  # MAXREPEAT
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


class MockMessage(Message):
    def __init__(self, ta_info):
        self.ta_info = ta_info
        self.errorlist = []
        self.messagetypetxt = "MockMessage "
        self.defmessage = MockGrammar()
        self.root = Node()


def test_message_repeating_field_mandatory_missing():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ".",
        "has_structure": True,
        "checkunknownentities": False,
    }
    msg = MockMessage(ta_info)

    # REP_FIELD is mandatory, but not present
    node = Node(record={"BOTSID": "REC1", "REC1": "REC", "REP_COMP": [{"SUB1": "val"}]})
    msg.root.append(node)

    msg.checkmessage(msg.root, msg.defmessage)

    assert any("is mandatory" in err for err in msg.errorlist)


def test_message_repeating_field_not_list():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ".",
        "has_structure": True,
        "checkunknownentities": False,
    }
    msg = MockMessage(ta_info)

    node = Node(record={"BOTSID": "REC1", "REC1": "REC", "REP_FIELD": "not_a_list"})
    msg.root.append(node)

    with pytest.raises(MappingFormatError) as exc:
        msg.checkmessage(msg.root, msg.defmessage)
    assert "must be a list" in str(exc.value)


def test_message_repeating_field_max_repeats():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ".",
        "has_structure": True,
        "checkunknownentities": False,
    }
    msg = MockMessage(ta_info)

    # REP_FIELD MAXREPEAT is 2, but we pass 3
    node = Node(
        record={
            "BOTSID": "REC1",
            "REC1": "REC",
            "REP_FIELD": ["v1", "v2", "v3"],
            "REP_COMP": [{"SUB1": "val"}],
        }
    )
    msg.root.append(node)

    msg.checkmessage(msg.root, msg.defmessage)

    assert any("occurs 3 times, max is 2" in err for err in msg.errorlist)


def test_message_repeating_field_empty_data():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ".",
        "has_structure": True,
        "checkunknownentities": False,
    }
    msg = MockMessage(ta_info)

    # REP_FIELD has empty strings, so it's considered empty and should fail mandatory check
    node = Node(
        record={
            "BOTSID": "REC1",
            "REC1": "REC",
            "REP_FIELD": ["", None],
            "REP_COMP": [{"SUB1": "val"}],
        }
    )
    msg.root.append(node)

    msg.checkmessage(msg.root, msg.defmessage)

    assert any("is mandatory" in err for err in msg.errorlist)


def test_message_repeating_composite_max_repeats():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ".",
        "has_structure": True,
        "checkunknownentities": False,
    }
    msg = MockMessage(ta_info)

    # REP_COMP MAXREPEAT is 2, but we pass 3
    node = Node(
        record={
            "BOTSID": "REC1",
            "REC1": "REC",
            "REP_FIELD": ["v1"],
            "REP_COMP": [{"SUB1": "val1"}, {"SUB1": "val2"}, {"SUB1": "val3"}],
        }
    )
    msg.root.append(node)

    msg.checkmessage(msg.root, msg.defmessage)

    assert any("occurs 3 times, max is 2" in err for err in msg.errorlist)


def test_message_repeating_composite_mandatory_subfield_missing():
    ta_info = {
        "lengthnumericbare": False,
        "decimaal": ".",
        "has_structure": True,
        "checkunknownentities": False,
    }
    msg = MockMessage(ta_info)

    # SUB1 is mandatory, but not passed
    node = Node(
        record={
            "BOTSID": "REC1",
            "REC1": "REC",
            "REP_FIELD": ["v1"],
            "REP_COMP": [{"SUB2": "val2"}],
        }
    )
    msg.root.append(node)

    msg.checkmessage(msg.root, msg.defmessage)

    assert any("is mandatory" in err for err in msg.errorlist)
