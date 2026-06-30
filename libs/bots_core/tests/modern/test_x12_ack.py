import pytest
from bots_core.domain.node import Node
from bots_core.domain.x12_ack import generate_997_ast


def test_generate_997_no_gs():
    in_node = Node({"BOTSID": "ST"})
    with pytest.raises(ValueError, match="Cannot generate 997: no GS segment found"):
        generate_997_ast(in_node)


def test_generate_997_root_is_gs():
    in_node = Node({"BOTSID": "GS", "GS01": "IN", "GS06": "123"})
    ast = generate_997_ast(in_node)

    assert ast.record["BOTSID"] == "ST"
    assert ast.record["ST01"] == "997"

    ak1 = ast.children[0]
    assert ak1.record["BOTSID"] == "AK1"
    assert ak1.record["AK101"] == "IN"
    assert ak1.record["AK102"] == "123"

    ak9 = ast.children[1]
    assert ak9.record["BOTSID"] == "AK9"
    assert ak9.record["AK901"] == "A"
    assert ak9.record["AK902"] == "1"


def test_generate_997_root_has_gs():
    in_node = Node({"BOTSID": "ISA"})
    gs = Node({"BOTSID": "GS", "GS01": "PO", "GS06": "456"})
    in_node.append(gs)

    ast = generate_997_ast(in_node)
    ak1 = ast.children[0]
    assert ak1.record["AK101"] == "PO"
    assert ak1.record["AK102"] == "456"


def test_generate_997_gs_st_count():
    in_node = Node({"BOTSID": "GS", "GS01": "IN", "GS06": "123"})
    st1 = Node({"BOTSID": "ST"})
    st2 = Node({"BOTSID": "ST"})
    in_node.append(st1)
    in_node.append(st2)

    ast = generate_997_ast(in_node)
    ak9 = ast.children[1]
    assert ak9.record["AK902"] == "2"
    assert ak9.record["AK903"] == "2"


def test_generate_997_isa_gs_st_count():
    in_node = Node({"BOTSID": "ISA"})
    gs = Node({"BOTSID": "GS", "GS01": "IN", "GS06": "123"})
    st1 = Node({"BOTSID": "ST"})
    st2 = Node({"BOTSID": "ST"})
    st3 = Node({"BOTSID": "ST"})
    gs.append(st1)
    gs.append(st2)
    gs.append(st3)
    in_node.append(gs)

    ast = generate_997_ast(in_node, error_list=["error1"])
    ak9 = ast.children[1]
    assert ak9.record["AK901"] == "R"
    assert ak9.record["AK902"] == "3"
    assert ak9.record["AK904"] == "0"  # Rejected, accepted is 0


def test_generate_997_gs_no_st_count():
    in_node = Node({"BOTSID": "GS", "GS01": "IN", "GS06": "123"})
    # No ST
    ast = generate_997_ast(in_node)
    ak9 = ast.children[1]
    assert ak9.record["AK902"] == "1"  # defaults to 1
