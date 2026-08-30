import pytest

from edi.core.bots.config.botsconfig import SFIELD, VALUE
from edi.core.bots.domain.message import Message, MessageRootError
from edi.core.bots.domain.models import create_field_definition, create_structure_node
from edi.core.bots.domain.node import Node


class MockGrammarForMessage:
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

        self.structure = [["REC1", 1, 2, 0, 0, ["REC1"], None]]
        self.recorddefs = {
            "REC1": [
                [
                    "BOTSID",
                    "M",
                    3,
                    "AN",
                    True,
                    0,
                    3,
                    "AN",
                    1,
                ],
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
            ]
        }
        self.recorddefs["REC1"] = [create_field_definition(f) for f in self.recorddefs["REC1"]]
        self.structure[0][6] = self.recorddefs["REC1"]
        self.structure = [create_structure_node({i: v for i, v in enumerate(self.structure[0])})]


class MockMessageForCheck(Message):
    def __init__(self, ta_info=None):
        if ta_info is None:
            ta_info = {
                "lengthnumericbare": False,
                "decimaal": ".",
                "has_structure": True,
                "checkunknownentities": False,
            }
        super().__init__(ta_info)
        self.messagetypetxt = "MockMessage "
        self.defmessage = MockGrammarForMessage()
        self.root = Node()


def test_display():
    lex_records = [
        [
            {VALUE: "SEG", SFIELD: 0},
            {VALUE: "F1", SFIELD: 0},
            {VALUE: "S1", SFIELD: 1},
            {VALUE: "R1", SFIELD: 2},
            {VALUE: "X", SFIELD: 3},
        ]
    ]
    Message.display(lex_records)


def test_manipulatemessagetype():
    msg = MockMessageForCheck()
    assert msg._manipulatemessagetype("type", None) == "type"


def test_checkonemessage_wrong_root():
    msg = MockMessageForCheck()
    node = Node(record={"BOTSID": "WRONG"})
    msg.root.append(node)
    with pytest.raises(MessageRootError, match="starts with record"):
        msg.checkmessage(msg.root, msg.defmessage)


def test_checkonemessage_min_occ():
    msg = MockMessageForCheck()
    msg.checkmessage(msg.root, msg.defmessage)
    assert any("occurs 0 times, min is 1" in err for err in msg.errorlist)


def test_checkonemessage_max_occ():
    msg = MockMessageForCheck()
    msg.root.append(Node(record={"BOTSID": "REC1", "REC1": "VAL"}))
    msg.root.append(Node(record={"BOTSID": "REC1", "REC1": "VAL"}))
    msg.root.append(Node(record={"BOTSID": "REC1", "REC1": "VAL"}))
    msg.checkmessage(msg.root, msg.defmessage)
    assert any("occurs 3 times, max is 2" in err for err in msg.errorlist)


def test_checkifrecordsingrammar_unknown_children():
    msg = MockMessageForCheck(
        {
            "lengthnumericbare": False,
            "decimaal": ".",
            "has_structure": True,
            "checkunknownentities": True,
        }
    )
    node = Node(record={"BOTSID": "REC1", "REC1": "VAL"})
    unknown_child = Node(record={"BOTSID": "UNKNOWN"})
    node.append(unknown_child)
    msg.root.append(node)

    msg.checkmessage(msg.root, msg.defmessage)
    assert any(
        "in message has children, but these are not in grammar" in err for err in msg.errorlist
    )
    assert not node.children
