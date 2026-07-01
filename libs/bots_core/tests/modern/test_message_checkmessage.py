"""
test_message_checkmessage.py
Tests for message.py business-logic: add2errorlist, checkforerrorlist,
mpathformat, and the high-value checkmessage / _canonicalfields paths.

These are exercised through parse_edi_file (integration) AND through
direct construction (unit) so we get maximum branch coverage.
"""

import json

import pytest
from bots_core.domain.exceptions import MessageError
from bots_core.domain.message import Message
from bots_core.facade import edi_to_json, json_to_edi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _x12_850(
    isa13="000000001",
    iea02="000000001",
    iea01="1",
    gs06="1",
    ge02="1",
    ge01="1",
    st02="0001",
    se02="0001",
    se01="5",  # ST + BEG + PO1 + CTT + SE = 5 segments (SE counts itself)
):
    """Build a parameterised X12 850 EDI string."""
    return (
        f"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        f"*210101*1200*U*00401*{isa13}*0*T*>~\r\n"
        f"GS*PO*SENDER*RECEIVER*20210101*1200*{gs06}*X*004010~\r\n"
        f"ST*850*{st02}~\r\n"
        f"BEG*00*SA*123456~\r\n"
        f"PO1*1*100*EA*10.5~\r\n"
        f"CTT*1~\r\n"
        f"SE*{se01}*{se02}~\r\n"
        f"GE*{ge01}*{ge02}~\r\n"
        f"IEA*{iea01}*{iea02}~\r\n"
    )


# ---------------------------------------------------------------------------
# mpathformat (static — pure logic, no I/O)
# ---------------------------------------------------------------------------


def test_mpathformat_single():
    assert Message.mpathformat(["UNH"]) == "UNH"


def test_mpathformat_multi():
    assert Message.mpathformat(["UNH", "NAD", "C080"]) == "UNH-NAD-C080"


def test_mpathformat_empty():
    assert Message.mpathformat([]) == ""


# ---------------------------------------------------------------------------
# add2errorlist / checkforerrorlist (unit via concrete subclass)
# ---------------------------------------------------------------------------


class _MockMessage:
    """Minimal concrete stand-in for Message to test error list logic."""

    def __init__(self):
        self.errorlist = []
        self.errorfatal = False
        self.messagetypetxt = ""

    add2errorlist = Message.add2errorlist
    checkforerrorlist = Message.checkforerrorlist
    try_to_retrieve_info = Message.try_to_retrieve_info


def test_add2errorlist_under_limit():
    m = _MockMessage()
    for i in range(5):
        m.add2errorlist(f"error {i}\n")
    assert len(m.errorlist) == 5
    assert "error 0" in m.errorlist[0]


def test_add2errorlist_cap_at_10():
    m = _MockMessage()
    for i in range(15):
        m.add2errorlist(f"error {i}\n")
    # 10 real errors + 1 "too many" sentinel = 11
    assert len(m.errorlist) == 11
    assert "too many" in m.errorlist[10].lower()


def test_add2errorlist_exactly_10_triggers_sentinel():
    """The sentinel [A51] is appended on the 11th call (when len == 10)."""
    m = _MockMessage()
    for i in range(10):
        m.add2errorlist(f"err {i}\n")
    # 10 errors stored; sentinel NOT yet triggered (len < 10 was False on 10th, len == 10 not hit)
    assert len(m.errorlist) == 10
    # The 11th call: len == 10 → sentinel appended
    m.add2errorlist("triggers sentinel\n")
    assert len(m.errorlist) == 11
    assert "too many" in m.errorlist[10].lower()
    # Further calls beyond sentinel should be a no-op
    m.add2errorlist("beyond cap\n")
    assert len(m.errorlist) == 11


def test_checkforerrorlist_raises_when_errors():
    m = _MockMessage()
    m.add2errorlist("[F05]: some field too big\n")
    with pytest.raises(MessageError) as exc_info:
        m.checkforerrorlist()
    assert "F05" in str(exc_info.value)


def test_checkforerrorlist_no_raise_when_clean():
    m = _MockMessage()
    # Should not raise
    m.checkforerrorlist()


# ---------------------------------------------------------------------------
# Integration: well-formed X12 round-trip verifies entire parse stack
# ---------------------------------------------------------------------------


def test_x12_parse_envelope_counts(patch_data_dir):
    """Correct envelopes → no errorlist entries."""
    edi = _x12_850()
    f = patch_data_dir / "test.edi"
    f.write_text(edi)
    result = json.loads(edi_to_json(str(f), editype="x12", messagetype="x12"))
    isa = result["children"][0]
    assert isa["record"]["BOTSID"] == "ISA"
    iea = isa["children"][-1]
    assert iea["record"]["BOTSID"] == "IEA"
    # ISA13 / IEA02 are numeric; parser normalises them (strips leading zeros)
    assert iea["record"]["IEA02"] in ("000000001", "1")
    assert iea["record"]["IEA01"] == "1"


def test_x12_mismatched_isa_iea_reference(patch_data_dir):
    """ISA13 ≠ IEA02 → error E13 in errorlist."""
    edi = _x12_850(isa13="111111111", iea02="999999999")
    f = patch_data_dir / "bad_ref.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E13" in e for e in obj.errorlist), obj.errorlist


def test_x12_wrong_iea01_count(patch_data_dir):
    """IEA01 says 2 groups but only 1 exists → error E14."""
    edi = _x12_850(iea01="2")  # wrong count
    f = patch_data_dir / "bad_count.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E14" in e for e in obj.errorlist), obj.errorlist


def test_x12_wrong_ge01_count(patch_data_dir):
    """GE01 says 2 transactions but only 1 ST exists → error E17."""
    edi = _x12_850(ge01="2")
    f = patch_data_dir / "bad_ge.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E17" in e for e in obj.errorlist), obj.errorlist


def test_x12_mismatched_gs_ge_reference(patch_data_dir):
    """GS06 ≠ GE02 → error E16."""
    edi = _x12_850(gs06="1", ge02="9")
    f = patch_data_dir / "bad_gsge_ref.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E16" in e for e in obj.errorlist), obj.errorlist


def test_x12_mismatched_st_se_reference(patch_data_dir):
    """ST02 ≠ SE02 → error E19."""
    edi = _x12_850(st02="0001", se02="9999")
    f = patch_data_dir / "bad_stse_ref.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E19" in e for e in obj.errorlist), obj.errorlist


def test_x12_wrong_se01_segment_count(patch_data_dir):
    """SE01 says 99 segments but only 6 exist → error E20."""
    edi = _x12_850(se01="99")
    f = patch_data_dir / "bad_se.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E20" in e for e in obj.errorlist), obj.errorlist


def test_x12_invalid_iea_count_non_numeric(patch_data_dir):
    """IEA01 = 'X' (not a number) → error E15."""
    edi = (
        "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        "*210101*1200*U*00401*000000001*0*T*>~\r\n"
        "GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~\r\n"
        "ST*850*0001~\r\n"
        "BEG*00*SA*123456~\r\n"
        "PO1*1*100*EA*10.5~\r\n"
        "CTT*1~\r\n"
        "SE*6*0001~\r\n"
        "GE*1*1~\r\n"
        "IEA*X*000000001~\r\n"  # IEA01 = 'X'
    )
    f = patch_data_dir / "bad_iea_nonnumeric.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    assert any("E15" in e for e in obj.errorlist), obj.errorlist


# ---------------------------------------------------------------------------
# Integration: parse + re-serialise (writer path)
# ---------------------------------------------------------------------------


def test_x12_roundtrip_preserves_all_segments(patch_data_dir):
    """Parse X12 → JSON → serialise back; all segments must still be present."""
    edi = _x12_850()
    f = patch_data_dir / "rt.edi"
    f.write_text(edi)
    j = edi_to_json(str(f), editype="x12", messagetype="x12")
    out = json_to_edi(j, editype="x12", messagetype="x12")
    for seg in ("ISA", "GS*", "ST*850", "BEG*", "PO1*", "CTT*", "SE*", "GE*", "IEA*"):
        assert seg in out, f"Segment {seg!r} missing from re-serialised output"
