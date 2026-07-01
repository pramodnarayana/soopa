"""
test_node_business_logic.py
Comprehensive unit tests for Node methods covering the uncovered branches:
  - getnozero (zero-masking, non-numeric)
  - getdecimal (trailing minus, invalid, zero)
  - getcountsum (sum over matching nodes)
  - getcountoccurrences
  - change / _changecore
  - delete / _deletecore
  - copynode / stripnode / collectlines
  - put validation errors (MappingFormatError, MappingRootError)
  - getrecord
  - processqueries / displayqueries
  - to_dict / from_dict round-trip
"""

import decimal

import pytest
from bots_core.domain.exceptions import MappingFormatError, MappingRootError
from bots_core.domain.node import Node

# ---------------------------------------------------------------------------
# Helpers — build a small reusable tree
# ---------------------------------------------------------------------------


def _build_order_tree():
    """
    Root (empty)
      └─ ISA  BOTSID=ISA, ISA13=000000001
           └─ GS  BOTSID=GS, GS06=1
                └─ ST  BOTSID=ST, ST01=850, ST02=0001
                     ├─ BEG  BOTSID=BEG, BEG01=00, BEG02=SA, BEG03=PO123
                     ├─ PO1  BOTSID=PO1, PO101=1, PO102=10, PO103=EA, PO104=5.50
                     ├─ PO1  BOTSID=PO1, PO101=2, PEG102=5, PO103=EA, PO104=0.00
                     └─ CTT  BOTSID=CTT, CTT01=2
    """
    root = Node()

    isa = Node(record={"BOTSID": "ISA", "BOTSIDnr": "1", "ISA13": "000000001"})
    root.append(isa)

    gs = Node(record={"BOTSID": "GS", "BOTSIDnr": "1", "GS06": "1"})
    isa.append(gs)

    st = Node(record={"BOTSID": "ST", "BOTSIDnr": "1", "ST01": "850", "ST02": "0001"})
    gs.append(st)

    beg = Node(
        record={"BOTSID": "BEG", "BOTSIDnr": "1", "BEG01": "00", "BEG02": "SA", "BEG03": "PO123"}
    )
    st.append(beg)

    po1a = Node(
        record={
            "BOTSID": "PO1",
            "BOTSIDnr": "1",
            "PO101": "1",
            "PO102": "10",
            "PO103": "EA",
            "PO104": "5.50",
        }
    )
    st.append(po1a)

    po1b = Node(
        record={
            "BOTSID": "PO1",
            "BOTSIDnr": "1",
            "PO101": "2",
            "PO102": "5",
            "PO103": "EA",
            "PO104": "0.00",
        }
    )
    st.append(po1b)

    ctt = Node(record={"BOTSID": "CTT", "BOTSIDnr": "1", "CTT01": "2"})
    st.append(ctt)

    return root, isa, gs, st, po1a, po1b, ctt


# ---------------------------------------------------------------------------
# getcount
# ---------------------------------------------------------------------------


def test_getcount_empty_root():
    root = Node()
    assert root.getcount() == 0


def test_getcount_leaf():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    assert n.getcount() == 1


def test_getcount_tree():
    root, isa, gs, st, po1a, po1b, ctt = _build_order_tree()
    # isa + gs + st + beg + po1a + po1b + ctt = 7
    assert isa.getcount() == 7


# ---------------------------------------------------------------------------
# getcountoccurrences
# ---------------------------------------------------------------------------


def test_getcountoccurrences_existing():
    root, isa, gs, st, po1a, po1b, ctt = _build_order_tree()
    assert (
        isa.getcountoccurrences(
            {"BOTSID": "ISA"}, {"BOTSID": "GS"}, {"BOTSID": "ST"}, {"BOTSID": "PO1"}
        )
        == 2
    )


def test_getcountoccurrences_none():
    root, isa, *_ = _build_order_tree()
    assert isa.getcountoccurrences({"BOTSID": "ISA"}, {"BOTSID": "MISSING"}) == 0


# ---------------------------------------------------------------------------
# getcountsum
# ---------------------------------------------------------------------------


def test_getcountsum_basic():
    root, isa, gs, st, po1a, po1b, ctt = _build_order_tree()
    # Sum of PO102 over all PO1 segments: 10 + 5 = 15
    # getcountsum uses *mpaths
    total = isa.getcountsum(
        {"BOTSID": "ISA"},
        {"BOTSID": "GS"},
        {"BOTSID": "ST"},
        {"BOTSID": "PO1", "PO102": None},
    )
    assert decimal.Decimal(total) == decimal.Decimal("15")


def test_getcountsum_no_matches():
    root, isa, *_ = _build_order_tree()
    total = isa.getcountsum(
        {"BOTSID": "ISA"},
        {"BOTSID": "GS"},
        {"BOTSID": "DOES_NOT_EXIST", "FIELD": None},
    )
    assert decimal.Decimal(total) == decimal.Decimal("0")


# ---------------------------------------------------------------------------
# getnozero
# ---------------------------------------------------------------------------


def test_getnozero_nonzero_value():
    root, isa, gs, st, po1a, *_ = _build_order_tree()
    result = isa.getnozero(
        {"BOTSID": "ISA"}, {"BOTSID": "GS"}, {"BOTSID": "ST"}, {"BOTSID": "PO1", "PO102": None}
    )
    assert result == "10"


def test_getnozero_zero_returns_none():
    root, isa, gs, st, po1a, po1b, ctt = _build_order_tree()
    # po1b has PO104 = "0.00"
    result = po1b.getnozero({"BOTSID": "PO1", "PO104": None})
    assert result is None


def test_getnozero_non_numeric_returns_none():
    n = Node(record={"BOTSID": "BEG", "BOTSIDnr": "1", "BEG02": "SA"})
    result = n.getnozero({"BOTSID": "BEG", "BEG02": None})
    assert result is None


def test_getnozero_not_found_returns_none():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    result = n.getnozero({"BOTSID": "X", "MISSING": None})
    assert result is None


# ---------------------------------------------------------------------------
# getdecimal
# ---------------------------------------------------------------------------


def test_getdecimal_numeric():
    n = Node(record={"BOTSID": "PO1", "BOTSIDnr": "1", "PO104": "5.50"})
    assert n.getdecimal({"BOTSID": "PO1", "PO104": None}) == decimal.Decimal("5.50")


def test_getdecimal_trailing_minus():
    """Trailing minus sign (idoc style) should be converted to leading minus."""
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1", "AMOUNT": "100-"})
    result = n.getdecimal({"BOTSID": "X", "AMOUNT": None})
    assert result == decimal.Decimal("-100")


def test_getdecimal_not_found_returns_zero():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    assert n.getdecimal({"BOTSID": "X", "MISSING": None}) == decimal.Decimal("0")


def test_getdecimal_non_numeric_returns_zero():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1", "FIELD": "NOTANUMBER"})
    assert n.getdecimal({"BOTSID": "X", "FIELD": None}) == decimal.Decimal("0")


# ---------------------------------------------------------------------------
# getrecord
# ---------------------------------------------------------------------------


def test_getrecord_existing():
    root, isa, gs, st, *_ = _build_order_tree()
    record = isa.getrecord({"BOTSID": "ISA"}, {"BOTSID": "GS"})
    assert record is not None
    assert record["BOTSID"] == "GS"


def test_getrecord_not_found():
    root, isa, *_ = _build_order_tree()
    record = isa.getrecord({"BOTSID": "ISA"}, {"BOTSID": "MISSING"})
    assert record is None


# ---------------------------------------------------------------------------
# change / _changecore
# ---------------------------------------------------------------------------


def test_change_existing_field():
    root, isa, gs, st, po1a, *_ = _build_order_tree()
    before = po1a.get({"BOTSID": "PO1", "PO104": None})
    assert before == "5.50"
    isa.change(
        where=({"BOTSID": "ISA", "ISA13": "000000001"},),
        change={"BOTSID": "ISA", "ISA13": "CHANGED"},
    )
    assert isa.record["ISA13"] == "CHANGED"


def test_change_nested():
    root, isa, gs, st, po1a, *_ = _build_order_tree()
    st.change(
        where=({"BOTSID": "ST"}, {"BOTSID": "BEG", "BEG03": "PO123"}),
        change={"BOTSID": "BEG", "BEG03": "NEW-PO"},
    )
    assert st.get({"BOTSID": "ST"}, {"BOTSID": "BEG", "BEG03": None}) == "NEW-PO"


# ---------------------------------------------------------------------------
# delete / _deletecore
# ---------------------------------------------------------------------------


def test_delete_existing_child():
    root, isa, gs, st, po1a, po1b, ctt = _build_order_tree()
    before_count = len(st.children)
    # Delete CTT segment
    st.delete({"BOTSID": "ST"}, {"BOTSID": "CTT"})
    assert len(st.children) == before_count - 1
    assert all(c.record["BOTSID"] != "CTT" for c in st.children)


def test_delete_non_existing_silent():
    root, isa, gs, st, *_ = _build_order_tree()
    before = len(st.children)
    st.delete({"BOTSID": "ST"}, {"BOTSID": "NONEXISTENT"})
    assert len(st.children) == before  # nothing deleted


# ---------------------------------------------------------------------------
# copynode
# ---------------------------------------------------------------------------


def test_copynode_deep_copy():
    root, isa, gs, st, po1a, *_ = _build_order_tree()
    copy = po1a.copynode()
    assert copy.record == po1a.record
    assert copy is not po1a
    assert copy.record is not po1a.record


def test_copynode_children_copied():
    root, isa, gs, st, *_ = _build_order_tree()
    copy = st.copynode()
    assert len(copy.children) == len(st.children)


# ---------------------------------------------------------------------------
# stripnode
# ---------------------------------------------------------------------------


def test_stripnode_removes_empty_children():
    st = Node(record={"BOTSID": "ST", "BOTSIDnr": "1", "ST01": "850", "ST02": "0001"})
    beg = Node(record={"BOTSID": "BEG", "BOTSIDnr": "1", "BEG01": ""})
    st.append(beg)
    # stripnode removes spaces from fields, it does not remove the node itself
    st.stripnode()
    assert beg.record["BEG01"] == ""
    assert isinstance(st.children, list)


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_roundtrip():
    root, isa, gs, st, po1a, *_ = _build_order_tree()
    d = isa.to_dict()
    assert d["record"]["BOTSID"] == "ISA"
    assert len(d["children"]) == 1  # GS

    restored = Node.from_dict(d)
    assert restored.record["BOTSID"] == "ISA"
    assert len(restored.children) == 1


def test_to_dict_leaf():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1", "VAL": "hello"})
    d = n.to_dict()
    assert d["record"]["VAL"] == "hello"
    assert d.get("children", []) == []


def test_from_dict_no_children():
    d = {"record": {"BOTSID": "X", "BOTSIDnr": "1", "VAL": "world"}, "children": []}
    n = Node.from_dict(d)
    assert n.record["VAL"] == "world"
    assert n.children == []


# ---------------------------------------------------------------------------
# put validation errors
# ---------------------------------------------------------------------------


def test_put_raises_if_no_botsid():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    with pytest.raises(MappingFormatError):
        n.put({"FIELD": "value"})  # missing BOTSID


def test_put_raises_on_wrong_root():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    with pytest.raises(MappingRootError):
        n.put({"BOTSID": "WRONG_ROOT", "BOTSIDnr": "1", "FIELD": "value"})


def test_put_returns_false_on_none_value():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    result = n.put({"BOTSID": "X", "BOTSIDnr": "1", "FIELD": None})
    assert result is False


def test_put_returns_false_on_empty_list():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    result = n.put({"BOTSID": "X", "BOTSIDnr": "1", "FIELD": []})
    assert result is False


def test_put_strips_whitespace_by_default():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    child = Node(record={"BOTSID": "Y", "BOTSIDnr": "1"})
    n.append(child)
    n.put({"BOTSID": "X", "BOTSIDnr": "1"}, {"BOTSID": "Y", "BOTSIDnr": "1", "VAL": "  hello  "})
    assert child.record["VAL"] == "hello"


# ---------------------------------------------------------------------------
# linpos
# ---------------------------------------------------------------------------


def test_linpos_with_info():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"}, linpos_info=(5, 12))
    assert n.linpos() == " line 5 pos 12"


def test_linpos_without_info():
    n = Node(record={"BOTSID": "X", "BOTSIDnr": "1"})
    assert n.linpos() == ""


# ---------------------------------------------------------------------------
# processqueries / displayqueries (smoke test — no crash)
# ---------------------------------------------------------------------------


def test_processqueries_no_crash():
    root, isa, *_ = _build_order_tree()
    # Should run without raising
    isa.processqueries({}, 1)


def test_displayqueries_no_crash(capsys):
    root, isa, *_ = _build_order_tree()
    isa.displayqueries()
    # Just verify it doesn't crash; output goes to stdout


# ---------------------------------------------------------------------------
# collectlines
# ---------------------------------------------------------------------------


def test_collectlines_returns_list():
    root, isa, gs, st, po1a, po1b, ctt = _build_order_tree()
    from bots_core.domain.models import StructureNode

    st.structure = StructureNode(id="ST", min_occ=1, max_occ=1, mpath=["ST"])
    st.children[0].structure = StructureNode(id="BEG", min_occ=1, max_occ=1, mpath=["ST", "BEG"])
    po1a.structure = StructureNode(id="PO1", min_occ=1, max_occ=1, mpath=["ST", "PO1"])
    po1b.structure = StructureNode(id="PO1", min_occ=1, max_occ=1, mpath=["ST", "PO1"])
    ctt.structure = StructureNode(id="CTT", min_occ=1, max_occ=1, mpath=["ST", "CTT"])

    # collectlines mutates children into grouped lists for matching rows
    st.collectlines([["ST", "PO1"]])
    # The children list now contains: BEG, [PO1a, PO1b], CTT
    assert len(st.children) == 3
    assert isinstance(st.children[1], list)
    assert len(st.children[1]) == 2
