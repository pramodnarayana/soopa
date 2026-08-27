import pytest

from edi.core.bots.domain.exceptions import MappingFormatError, MappingRootError
from edi.core.bots.domain.node import Node


def test_node_putraw_invalid_mpaths():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})

    with pytest.raises(MappingFormatError):
        node.putraw()

    with pytest.raises(MappingFormatError):
        node.putraw("NOT_DICT")

    with pytest.raises(MappingFormatError):
        node.putraw({"KEY": "VAL"})  # No BOTSID

    with pytest.raises(MappingFormatError):
        node.putraw({"BOTSID": "ROOT", 123: "VAL"})  # Key is not string


def test_node_putraw_none_value():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    assert node.putraw({"BOTSID": "ROOT"}, {"BOTSID": "CHILD", "F1": None}) is False


def test_node_putraw_empty_list():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    assert node.putraw({"BOTSID": "ROOT"}, {"BOTSID": "CHILD", "F1": []}) is False


def test_node_putraw_wrong_root():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    with pytest.raises(MappingRootError):
        node.putraw({"BOTSID": "WRONG_ROOT"})


def test_node_putloop_invalid_mpaths():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})

    with pytest.raises(MappingFormatError):
        node.putloop()

    with pytest.raises(MappingFormatError):
        node.putloop("NOT_DICT")

    with pytest.raises(MappingFormatError):
        node.putloop({"KEY": "VAL"})  # No BOTSID

    with pytest.raises(MappingFormatError):
        node.putloop({"BOTSID": "ROOT", 123: "VAL"})  # Key is not string


def test_node_putloop_none_value():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    with pytest.raises(ValueError, match="Cannot putloop None value"):
        node.putloop({"BOTSID": "ROOT"}, {"BOTSID": "CHILD", "F1": None})


def test_node_putloop_single_mpath_same():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    res = node.putloop({"BOTSID": "ROOT"})
    assert res == node


def test_node_putloop_wrong_root():
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    with pytest.raises(MappingRootError):
        node.putloop({"BOTSID": "WRONG_ROOT"})


def test_node_display(capsys) -> None:
    node = Node(record={"BOTSID": "ROOT", "BOTSIDnr": "1"})
    child = Node(record={"BOTSID": "CHILD", "BOTSIDnr": "1"})
    node.append(child)

    node.display()

    captured = capsys.readouterr()
    assert "Displaying all nodes in node tree:" in captured.out
    assert "ROOT" in captured.out
    assert "CHILD" in captured.out
