import pytest
from bots_core.domain.exceptions import MappingRootError
from bots_core.domain.message import Message
from bots_core.domain.node import Node


class MockMessage(Message):
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
        self.root = Node()
        self.root.record = None


def test_message_empty_root_errors():
    msg = MockMessage()
    with pytest.raises(MappingRootError):
        msg.getrecord("REC1")
    with pytest.raises(MappingRootError):
        msg.change("REC1", "val")
    with pytest.raises(MappingRootError):
        msg.delete("REC1")
    with pytest.raises(MappingRootError):
        msg.get("REC1")
    with pytest.raises(MappingRootError):
        msg.getnozero("REC1")
    with pytest.raises(MappingRootError):
        msg.getdecimal("REC1")
    with pytest.raises(MappingRootError):
        msg.getcountsum("REC1")
    with pytest.raises(MappingRootError):
        msg.sort("REC1")


def test_message_put_empty_root_with_children():
    msg = MockMessage()
    msg.root.append(Node(record={"REC": "1"}))
    with pytest.raises(MappingRootError):
        msg.put("REC2")
    with pytest.raises(MappingRootError):
        msg.putraw("REC2")


def test_message_putloop_dummy_root_mpath_too_long():
    msg = MockMessage()
    with pytest.raises(MappingRootError, match="mpath too long"):
        msg.putloop("REC1", "REC2")


def test_message_putloop_dummy_root_success():
    msg = MockMessage()
    node = msg.putloop({"BOTSID": "REC1"})
    assert node.record == {"BOTSID": "REC1", "BOTSIDnr": "1"}
    assert msg.root.children[-1] == node


def test_message_getloop_including_mpath():
    msg = MockMessage()
    child = Node(record={"BOTSID": "REC1"})
    msg.root.append(child)
    results = list(msg.getloop_including_mpath({"BOTSID": "REC1"}))

    msg.root.record = {"BOTSID": "ROOT"}
    results = list(msg.getloop_including_mpath({"BOTSID": "REC1"}))
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests for delegation methods when root IS populated (covers the happy paths)
# ---------------------------------------------------------------------------


def _make_msg_with_root(record=None):
    """Helper: build a MockMessage with a real root record."""
    msg = MockMessage()
    msg.root.record = record or {"BOTSID": "MSG", "BOTSIDnr": "1", "FLD": "value"}
    return msg


def test_message_get_with_real_root():
    """get() with a real root uses mpath-style dicts: last dict has field=None to retrieve."""
    msg = _make_msg_with_root()
    result = msg.get({"BOTSID": "MSG", "FLD": None})
    assert result == "value"


def test_message_get_missing_field_returns_none():
    msg = _make_msg_with_root()
    result = msg.get({"BOTSID": "MSG", "NOSUCHFIELD": None})
    assert result is None


def test_message_getnozero_with_real_root_numeric():
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1", "QTY": "0"})
    result = msg.getnozero({"BOTSID": "MSG", "QTY": None})
    assert result is None  # zero should return None


def test_message_getnozero_nonzero():
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1", "QTY": "5"})
    result = msg.getnozero({"BOTSID": "MSG", "QTY": None})
    assert result == "5"


def test_message_getdecimal_with_real_root():
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1", "AMT": "10.50"})
    result = msg.getdecimal({"BOTSID": "MSG", "AMT": None})
    from decimal import Decimal

    assert result == Decimal("10.50")


def test_message_change_with_real_root():
    """change() expects a tuple of dicts for 'where' and a dict for 'change'."""
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1", "FLD": "old"})
    # where is a tuple of dpath dicts; change is a dict of field->value updates
    msg.change(({"BOTSID": "MSG"},), {"FLD": "new"})
    assert msg.root.record["FLD"] == "new"


def test_message_delete_with_real_root():
    """delete() removes the matching child node from the tree."""
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1"})
    child = Node(record={"BOTSID": "CHILD", "BOTSIDnr": "1", "VAL": "x"})
    msg.root.append(child)
    deleted = msg.delete({"BOTSID": "MSG"}, {"BOTSID": "CHILD"})
    assert deleted is True
    assert child not in msg.root.children


def test_message_getcountsum_with_real_root():
    """getcountsum sums numeric field values across matching nodes."""
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1"})
    child1 = Node(record={"BOTSID": "LIN", "BOTSIDnr": "1", "QTY": "10"})
    child2 = Node(record={"BOTSID": "LIN", "BOTSIDnr": "1", "QTY": "5"})
    msg.root.append(child1)
    msg.root.append(child2)
    total = msg.getcountsum({"BOTSID": "MSG"}, {"BOTSID": "LIN", "QTY": None})
    assert total == "15"  # node returns str(Decimal)


def test_message_sort_with_real_root_noop():
    """sort with a proper mpath format should not raise."""
    msg = _make_msg_with_root({"BOTSID": "MSG", "BOTSIDnr": "1"})
    child_a = Node(record={"BOTSID": "LIN", "BOTSIDnr": "1", "SEQ": "2"})
    child_b = Node(record={"BOTSID": "LIN", "BOTSIDnr": "1", "SEQ": "1"})
    msg.root.append(child_a)
    msg.root.append(child_b)
    # sort by SEQ field
    msg.sort({"BOTSID": "MSG"}, {"BOTSID": "LIN", "SEQ": None})


def test_message_getcount():
    msg = MockMessage()
    msg.root.record = None
    msg.putloop({"BOTSID": "REC"})
    assert msg.getcount() >= 1


def test_message_getcountoccurrences():
    msg = MockMessage()
    msg.root.record = None
    msg.putloop({"BOTSID": "REC"})
    msg.putloop({"BOTSID": "REC"})
    count = msg.getcountoccurrences({"BOTSID": "REC"})
    assert count == 2


def test_message_put_with_real_root_no_children():
    """put() on a root with record set and no children should not raise MappingRootError."""
    msg = MockMessage()
    msg.root.record = {"BOTSID": "MSG", "BOTSIDnr": "1"}
    try:
        msg.put({"BOTSID": "MSG"}, "FLD", "val")
    except MappingRootError:
        pytest.fail("put() raised MappingRootError unexpectedly")
    except Exception:
        pass  # other errors from node.put are acceptable here


def test_message_putraw_with_real_root_no_children():
    """putraw() on a root with record set and no children should not raise MappingRootError."""
    msg = MockMessage()
    msg.root.record = {"BOTSID": "MSG", "BOTSIDnr": "1"}
    try:
        msg.putraw({"BOTSID": "MSG"}, "FLD", "raw_val")
    except MappingRootError:
        pytest.fail("putraw() raised MappingRootError unexpectedly")
    except Exception:
        pass


def test_message_getloop_with_real_root():
    msg = _make_msg_with_root()
    child = Node(record={"BOTSID": "CHILD", "BOTSIDnr": "1"})
    msg.root.append(child)
    results = list(msg.getloop({"BOTSID": "MSG"}, {"BOTSID": "CHILD"}))
    assert len(results) == 1
    assert results[0].record["BOTSID"] == "CHILD"


def test_message_getloop_with_dummy_root():
    msg = MockMessage()  # root.record is None
    child = Node(record={"BOTSID": "MSG", "BOTSIDnr": "1"})
    inner = Node(record={"BOTSID": "CHILD", "BOTSIDnr": "1"})
    child.append(inner)
    msg.root.append(child)
    results = list(msg.getloop({"BOTSID": "MSG"}, {"BOTSID": "CHILD"}))
    assert len(results) == 1


def test_message_getrecord_with_real_root():
    """getrecord() returns the raw record dict (not a Node) for the matched mpath."""
    msg = _make_msg_with_root()
    result = msg.getrecord({"BOTSID": "MSG"})
    assert result is not None
    assert isinstance(result, dict)
    assert result["BOTSID"] == "MSG"


# ---------------------------------------------------------------------------
# Tests for grammar.Grammar display and _manipulatefieldformat
# ---------------------------------------------------------------------------


def test_grammar_display(capsys):
    """grammar.display() should print mpath and fields without error."""
    from bots_core.domain.grammar.grammar import Grammar
    from bots_core.domain.models import FieldDefinition, StructureNode

    # Build a minimal structure node manually
    field = FieldDefinition(
        id="FLD01",
        mandatory=False,
        min_length=0,
        length=10,
        format="AN",
        bformat="A",
        decimals=0,
        max_repeat=1,
        is_field=True,
        subfields=[],
    )
    struct_node = StructureNode(
        id="TST",
        mpath=["TST"],
        botsidnr="1",
        min_occ=0,
        max_occ=1,
        fields=[field],
        level=[],
        subtranslation=None,
    )

    # Instantiate Grammar without calling __init__ (avoid botsimport)
    g = object.__new__(Grammar)
    g.grammarname = "test"
    g.display([struct_node])

    captured = capsys.readouterr()
    assert "TST" in captured.out


def test_grammar_manipulatefieldformat_known():
    """_manipulatefieldformat with known format key should set BFORMAT."""
    from bots_core.domain.grammar.grammar import Grammar
    from bots_core.infrastructure.config.botsconfig import BFORMAT, FORMAT, ID

    g = object.__new__(Grammar)
    g.grammarname = "test"
    g.formatconvert = {"AN": "A", "N": "D"}

    field = {ID: "F01", FORMAT: "AN"}
    g._manipulatefieldformat(field, "REC01")
    assert field[BFORMAT] == "A"


def test_grammar_manipulatefieldformat_unknown_raises():
    """_manipulatefieldformat with unknown format key should raise GrammarError."""
    from bots_core.domain.exceptions import GrammarError
    from bots_core.domain.grammar.grammar import Grammar
    from bots_core.infrastructure.config.botsconfig import FORMAT, ID

    g = object.__new__(Grammar)
    g.grammarname = "test"
    g.formatconvert = {"AN": "A"}

    field = {ID: "F01", FORMAT: "BADFORMAT"}
    with pytest.raises(GrammarError, match="format"):
        g._manipulatefieldformat(field, "REC01")


def test_grammar_syntax_not_dict_raises(monkeypatch):
    """Grammar.__init__ raises GrammarError if syntax is not a dict."""
    from bots_core.domain.exceptions import GrammarError
    from bots_core.domain.grammar.grammar import Grammar
    from bots_core.utils import botslib

    class MockModule:
        syntax = "not a dict"

    monkeypatch.setattr(botslib, "botsimport", lambda *a: (MockModule(), "test"))
    with pytest.raises(GrammarError, match="syntax is not a dict"):
        Grammar("grammars", "edifact", "orders")
