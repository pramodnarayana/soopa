from bots_core.domain.node import Node
from bots_core.utils import botslib


def test_node_creation_and_children():
    n = Node({"BOTSID": "HEA", "field1": "val1"})
    assert n.record["BOTSID"] == "HEA"
    assert n.record["field1"] == "val1"

    child1 = Node({"BOTSID": "LIN", "item": "apple"})
    n.append(child1)

    assert len(n.children) == 1
    assert n.children[0].record["item"] == "apple"


def test_node_queries():
    n = Node({"BOTSID": "HEA", "field1": "val1"})
    child1 = Node({"BOTSID": "LIN", "item": "apple"})
    child2 = Node({"BOTSID": "LIN", "item": "banana"})
    subchild = Node({"BOTSID": "QTY", "amount": "10"})
    child1.append(subchild)

    n.append(child1)
    n.append(child2)

    # Test getrecord
    res = n.getrecord({"BOTSID": "HEA"})
    assert res["BOTSID"] == "HEA"

    # Test queries
    assert n.get({"BOTSID": "HEA"}, {"BOTSID": "LIN"}, {"BOTSID": "QTY", "amount": None}) == "10"

    # Test getcount
    assert n.getcount() == 4
    assert n.getcountoccurrences({"BOTSID": "HEA"}, {"BOTSID": "LIN"}) == 2


def test_node_mutation():
    n = Node({"BOTSID": "HEA"})
    n.put({"BOTSID": "HEA"}, {"BOTSID": "LIN", "new_field": "123"})

    # We should have appended a child LIN
    assert len(n.children) == 1
    assert n.children[0].record["new_field"] == "123"


def test_botslib_dirshouldbethere(tmp_path):
    test_dir = tmp_path / "testdir"
    assert not test_dir.exists()

    botslib.dirshouldbethere(str(test_dir))
    assert test_dir.exists()
