"""
test_node_advanced.py — Tests for advanced node.py functionality.
Targets the many uncovered methods: getloop, enhancedget, sort, putloop, etc.
"""

import pytest
from bots_core.domain.exceptions import MappingFormatError
from bots_core.domain.node import Node

# ---------------------------------------------------------------------------
# getloop
# ---------------------------------------------------------------------------


def test_getloop_root_only():
    n = Node({"BOTSID": "UNB"})
    loops = list(n.getloop({"BOTSID": "UNB"}))
    assert loops == [n]


def test_getloop_children():
    root = Node({"BOTSID": "UNB"})
    child = Node({"BOTSID": "UNH", "BOTSIDnr": "1"})
    root.append(child)
    loops = list(root.getloop({"BOTSID": "UNB"}, {"BOTSID": "UNH"}))
    assert len(loops) == 1
    assert loops[0] is child


def test_getloop_multiple_children():
    root = Node({"BOTSID": "ISA"})
    for i in range(3):
        root.append(Node({"BOTSID": "GS", "GS01": str(i)}))
    gs_nodes = list(root.getloop({"BOTSID": "ISA"}, {"BOTSID": "GS"}))
    assert len(gs_nodes) == 3
    assert [n.record["GS01"] for n in gs_nodes] == ["0", "1", "2"]


def test_getloop_nested():
    root = Node({"BOTSID": "ISA"})
    gs = Node({"BOTSID": "GS"})
    root.append(gs)
    st = Node({"BOTSID": "ST"})
    gs.append(st)

    # Traverse 3 levels: ISA -> GS -> ST
    results = list(root.getloop({"BOTSID": "ISA"}, {"BOTSID": "GS"}, {"BOTSID": "ST"}))
    assert len(results) == 1
    assert results[0] is st


def test_getloop_no_match():
    root = Node({"BOTSID": "ISA"})
    root.append(Node({"BOTSID": "GS"}))
    # Looking for ST directly under ISA — shouldn't exist
    results = list(root.getloop({"BOTSID": "ISA"}, {"BOTSID": "ST"}))
    assert results == []


# ---------------------------------------------------------------------------
# enhancedget
# ---------------------------------------------------------------------------


def test_enhancedget_with_string_literal():
    """When passed a plain string, enhancedget returns that string unchanged."""
    n = Node({"BOTSID": "UNH", "0062": "REF001"})
    # A string is treated as a constant — returned as-is
    assert n.enhancedget("SOME_CONSTANT") == "SOME_CONSTANT"


def test_enhancedget_with_dict():
    """When passed a dict mpath, enhancedget does a single get()."""
    n = Node({"BOTSID": "UNH", "0062": "REF001"})
    result = n.enhancedget({"BOTSID": "UNH", "0062": None})
    assert result == "REF001"


def test_enhancedget_with_tuple():
    """When passed a tuple, enhancedget traverses multiple levels."""
    root = Node({"BOTSID": "UNB"})
    child = Node({"BOTSID": "UNZ", "0036": "5"})
    root.append(child)
    result = root.enhancedget(({"BOTSID": "UNB"}, {"BOTSID": "UNZ", "0036": None}))
    assert result == "5"


def test_enhancedget_with_callable():
    """When passed a callable, enhancedget calls it with thisnode=self."""
    n = Node({"BOTSID": "UNH", "0062": "REF999"})
    result = n.enhancedget(lambda thisnode: thisnode.record.get("0062"))
    assert result == "REF999"


def test_enhancedget_with_list():
    """When passed a list, results are concatenated."""
    n = Node({"BOTSID": "UNH", "0062": "REF"})
    result = n.enhancedget(["PREFIX_", {"BOTSID": "UNH", "0062": None}])
    assert result == "PREFIX_REF"


# ---------------------------------------------------------------------------
# getrecord
# ---------------------------------------------------------------------------


def test_getrecord_top_level():
    root = Node({"BOTSID": "UNB"})
    result = root.getrecord({"BOTSID": "UNB"})
    assert result["BOTSID"] == "UNB"


def test_getrecord_nested():
    root = Node({"BOTSID": "UNB"})
    unz = Node({"BOTSID": "UNZ", "0036": "3"})
    root.append(unz)
    result = root.getrecord({"BOTSID": "UNB"}, {"BOTSID": "UNZ"})
    assert result["0036"] == "3"


def test_getrecord_not_found():
    root = Node({"BOTSID": "UNB"})
    result = root.getrecord({"BOTSID": "UNB"}, {"BOTSID": "NOTEXIST"})
    assert result is None


# ---------------------------------------------------------------------------
# get (with None sentinel for field extraction)
# ---------------------------------------------------------------------------


def test_get_extracts_field():
    root = Node({"BOTSID": "ISA"})
    root.append(Node({"BOTSID": "IEA", "IEA01": "7"}))
    result = root.get({"BOTSID": "ISA"}, {"BOTSID": "IEA", "IEA01": None})
    assert result == "7"


def test_get_returns_none_on_missing_node():
    root = Node({"BOTSID": "ISA"})
    result = root.get({"BOTSID": "ISA"}, {"BOTSID": "NONE", "NONE01": None})
    assert result is None


def test_get_returns_none_on_missing_field():
    root = Node({"BOTSID": "ISA"})
    root.append(Node({"BOTSID": "IEA"}))  # no IEA01
    result = root.get({"BOTSID": "ISA"}, {"BOTSID": "IEA", "IEA01": None})
    assert result is None


# ---------------------------------------------------------------------------
# put
# ---------------------------------------------------------------------------


def test_put_creates_child():
    root = Node({"BOTSID": "ISA"})
    root.put({"BOTSID": "ISA"}, {"BOTSID": "GS", "GS01": "PO"})
    assert len(root.children) == 1
    assert root.children[0].record["GS01"] == "PO"


def test_put_reuses_existing_child():
    root = Node({"BOTSID": "ISA"})
    root.put({"BOTSID": "ISA"}, {"BOTSID": "GS", "GS01": "PO"})
    # Putting again to same BOTSID — should reuse the existing node
    root.put({"BOTSID": "ISA"}, {"BOTSID": "GS", "GS02": "SENDER"})
    assert len(root.children) == 1
    assert root.children[0].record["GS02"] == "SENDER"


def test_putloop_creates_multiple():
    root = Node({"BOTSID": "ISA"})
    root.putloop({"BOTSID": "ISA"}, {"BOTSID": "GS", "GS01": "PO"})
    root.putloop({"BOTSID": "ISA"}, {"BOTSID": "GS", "GS01": "IN"})
    # putloop always appends
    gs_nodes = [c for c in root.children if c.record["BOTSID"] == "GS"]
    assert len(gs_nodes) == 2


# ---------------------------------------------------------------------------
# getcount / getcountoccurrences
# ---------------------------------------------------------------------------


def test_getcount_flat():
    root = Node({"BOTSID": "ST"})
    for botsid in ("BEG", "PO1", "CTT", "SE"):
        root.append(Node({"BOTSID": botsid}))
    # Segment count = 1 (self) + 4 children = 5
    assert root.getcount() == 5


def test_getcount_nested():
    root = Node({"BOTSID": "ST"})
    po1 = Node({"BOTSID": "PO1"})
    po1.append(Node({"BOTSID": "SLN"}))
    root.append(po1)
    # 1 (root) + 1 (PO1) + 1 (SLN) = 3
    assert root.getcount() == 3


def test_getcountoccurrences_correct():
    root = Node({"BOTSID": "GS"})
    root.append(Node({"BOTSID": "ST"}))
    root.append(Node({"BOTSID": "ST"}))
    root.append(Node({"BOTSID": "GE"}))
    count = root.getcountoccurrences({"BOTSID": "GS"}, {"BOTSID": "ST"})
    assert count == 2


def test_getcountoccurrences_zero():
    root = Node({"BOTSID": "GS"})
    root.append(Node({"BOTSID": "GE"}))
    count = root.getcountoccurrences({"BOTSID": "GS"}, {"BOTSID": "ST"})
    assert count == 0


# ---------------------------------------------------------------------------
# sort
# ---------------------------------------------------------------------------


def test_sort_children_by_field():
    root = Node({"BOTSID": "ISA"})
    root.append(Node({"BOTSID": "GS", "GS01": "PO"}))
    root.append(Node({"BOTSID": "GS", "GS01": "AB"}))
    root.append(Node({"BOTSID": "GS", "GS01": "ZZ"}))

    root.sort({"BOTSID": "ISA"}, {"BOTSID": "GS", "GS01": None})
    values = [c.record["GS01"] for c in root.children]
    assert values == ["AB", "PO", "ZZ"]


def test_node_change_success():
    root = Node({"BOTSID": "HEA", "FLD1": "A"})
    child2 = Node({"BOTSID": "LIN", "FLD2": "B"})
    root.append(child2)

    where = ({"BOTSID": "HEA", "FLD1": "A"}, {"BOTSID": "LIN", "FLD2": "B"})
    change = {"FLD2": "C", "NEWFLD": "D"}

    assert root.change(where, change) is True
    assert child2.record["FLD2"] == "C"
    assert child2.record["NEWFLD"] == "D"


def test_node_change_invalid_change_type():
    root = Node()
    with pytest.raises(MappingFormatError):
        root.change(({"BOTSID": "HEA"},), "not_a_dict")


def test_node_change_invalid_key_type():
    root = Node()
    child = Node({"BOTSID": "HEA"})
    root.append(child)
    with pytest.raises(MappingFormatError):
        root.change(({"BOTSID": "HEA"},), {1: "val"})


def test_node_change_delete_key():
    root = Node({"BOTSID": "HEA", "FLD1": "A"})
    root.change(({"BOTSID": "HEA"},), {"FLD1": None})
    assert "FLD1" not in root.record


def test_node_delete_success():
    root = Node({"BOTSID": "HEA", "FLD1": "A"})
    child2 = Node({"BOTSID": "LIN", "FLD2": "B"})
    root.append(child2)

    assert len(root.children) == 1
    # Delete child2
    assert root.delete({"BOTSID": "HEA"}, {"BOTSID": "LIN"}) is True
    assert len(root.children) == 0


def test_node_delete_single_dict_not_allowed():
    root = Node()
    with pytest.raises(MappingFormatError):
        root.delete({"BOTSID": "HEA"})


def test_node_delete_not_found():
    root = Node()
    child1 = Node({"BOTSID": "HEA"})
    root.append(child1)
    assert root.delete({"BOTSID": "HEA"}, {"BOTSID": "LIN"}) is False


def test_getloop_including_mpath():
    root = Node({"BOTSID": "HEA", "FLD1": "A"})
    child2 = Node({"BOTSID": "LIN", "FLD2": "B"})
    root.append(child2)

    result = list(root.getloop_including_mpath({"BOTSID": "HEA"}, {"BOTSID": "LIN"}))
    assert len(result) == 1
    assert len(result[0]) == 2
    assert result[0][0]["BOTSID"] == "HEA"
    assert result[0][1] is child2


def test_getnozero():
    root = Node({"BOTSID": "ROOT"})
    root.append(Node({"BOTSID": "HEA", "FLD1": "100.5", "BOTSIDnr": "1"}))
    root.append(Node({"BOTSID": "HEA", "FLD1": "0.0", "BOTSIDnr": "1"}))
    root.append(Node({"BOTSID": "HEA", "FLD1": "abc", "BOTSIDnr": "1"}))

    assert root.getnozero({"BOTSID": "ROOT"}, {"BOTSID": "HEA", "FLD1": None}) == "100.5"
    assert (
        root.getnozero(
            {"BOTSID": "ROOT"}, {"BOTSID": "HEA", "FLD1": "0.0"}, {"BOTSID": "HEA", "FLD1": None}
        )
        is None
    )


def test_getdecimal():
    root = Node({"BOTSID": "ROOT"})
    root.append(
        Node({"BOTSID": "HEA", "FLD1": "100.5", "FLD2": "100.5-", "FLD3": "abc", "BOTSIDnr": "1"})
    )

    import decimal

    assert root.getdecimal({"BOTSID": "ROOT"}, {"BOTSID": "HEA", "FLD1": None}) == decimal.Decimal(
        "100.5"
    )
    assert root.getdecimal({"BOTSID": "ROOT"}, {"BOTSID": "HEA", "FLD2": None}) == decimal.Decimal(
        "-100.5"
    )
    assert root.getdecimal({"BOTSID": "ROOT"}, {"BOTSID": "HEA", "FLD3": None}) == decimal.Decimal(
        "0"
    )
    assert root.getdecimal(
        {"BOTSID": "ROOT"}, {"BOTSID": "HEA", "MISSING": None}
    ) == decimal.Decimal("0")
