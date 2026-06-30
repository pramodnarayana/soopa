"""
test_inmessage_advanced.py
Tests for bots_core.domain.inmessage parsing loops (nextmessage) and missing coverage.
"""

from bots_core.domain.inmessage import Inmessage
from bots_core.domain.node import Node


class MockDefMessage:
    def __init__(self):
        self.nextmessage = None
        self.nextmessage2 = None
        self.nextmessageblock = None


def test_nextmessage_with_preprocess_nodes():
    msg = Inmessage(ta_info={"preprocess_nodes": None})
    msg.defmessage = MockDefMessage()
    msg.root = Node()

    preprocess_called = False

    def mock_preprocess(thisnode):
        nonlocal preprocess_called
        preprocess_called = True

    msg.ta_info["preprocess_nodes"] = mock_preprocess

    # Run the generator
    list(msg.nextmessage())
    assert preprocess_called


def test_nextmessage_split_by_nextmessage():
    msg = Inmessage(ta_info={"preprocess_nodes": None})
    msg.defmessage = MockDefMessage()
    msg.defmessage.nextmessage = ({"BOTSID": "ST"},)

    root = Node()
    st1 = Node(record={"BOTSID": "ST", "BOTSIDnr": "1", "ST01": "1"})
    st2 = Node(record={"BOTSID": "ST", "BOTSIDnr": "1", "ST01": "2"})
    root.append(st1)
    root.append(st2)
    msg.root = root

    messages = list(msg.nextmessage())
    assert len(messages) == 2
    assert msg.ta_info["total_number_of_messages"] == 2
    assert messages[0].ta_info["message_number"] == 1
    assert messages[1].ta_info["message_number"] == 2
    assert messages[0].root.record["ST01"] == "1"


def test_nextmessage_split_by_nextmessage2():
    msg = Inmessage(ta_info={"preprocess_nodes": None})
    msg.defmessage = MockDefMessage()
    msg.defmessage.nextmessage = ({"BOTSID": "ST"},)
    msg.defmessage.nextmessage2 = ({"BOTSID": "UNH"},)

    root = Node()
    unh1 = Node(record={"BOTSID": "UNH", "BOTSIDnr": "1"})
    unh2 = Node(record={"BOTSID": "UNH", "BOTSIDnr": "1"})
    root.append(unh1)
    root.append(unh2)
    msg.root = root

    messages = list(msg.nextmessage())
    # nextmessage2 is evaluated after nextmessage finishes its generator loop
    # Wait, nextmessage loop yields over nextmessage. Since there are no STs, it yields 0.
    # Then it checks nextmessage2 and yields UNHs.
    assert len(messages) == 2
    assert msg.ta_info["total_number_of_messages"] == 2


def test_nextmessage_split_by_nextmessageblock():
    msg = Inmessage(ta_info={"preprocess_nodes": None})
    msg.defmessage = MockDefMessage()
    msg.defmessage.nextmessageblock = {"BOTSID": "ROW", "KEY": None}

    root = Node()
    row1 = Node(record={"BOTSID": "ROW", "BOTSIDnr": "1", "KEY": "A"})
    row2 = Node(record={"BOTSID": "ROW", "BOTSIDnr": "1", "KEY": "A"})
    row3 = Node(record={"BOTSID": "ROW", "BOTSIDnr": "1", "KEY": "B"})
    root.append(row1)
    root.append(row2)
    root.append(row3)
    msg.root = root

    messages = list(msg.nextmessage())
    # Should split into two messages: group A and group B
    assert len(messages) == 2
    assert msg.ta_info["total_number_of_messages"] == 2

    # First message has 2 rows
    assert len(messages[0].root.children) == 2
    # Second message has 1 row
    assert len(messages[1].root.children) == 1


def test_nextmessage_fallback_pass_all():
    msg = Inmessage(ta_info={"preprocess_nodes": None})
    msg.defmessage = MockDefMessage()

    root = Node()
    child1 = Node(record={"BOTSID": "C1"})
    child2 = Node(record={"BOTSID": "C2"})
    root.append(child1)
    root.append(child2)
    msg.root = root

    msg.ta_info["pass_all"] = True
    messages = list(msg.nextmessage())
    assert len(messages) == 1
    assert len(messages[0].root.children) == 2


def test_nextmessage_fallback_children():
    msg = Inmessage(ta_info={"preprocess_nodes": None})
    msg.defmessage = MockDefMessage()

    root = Node()
    child1 = Node(record={"BOTSID": "C1"})
    child2 = Node(record={"BOTSID": "C2"})
    root.append(child1)
    root.append(child2)
    msg.root = root

    messages = list(msg.nextmessage())
    assert len(messages) == 2
    assert messages[0].root.record["BOTSID"] == "C1"
