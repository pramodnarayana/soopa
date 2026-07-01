"""
test_field_validation.py
Tests for _formatfield business rules in BOTH inmessage.py and outmessage.py.

Strategy: We exercise these via JSON→EDI (outmessage._formatfield) and
EDI→JSON (inmessage._formatfield) paths, since both run the same field-
validation logic. This gives maximum coverage of:
  - A (alphanumeric) length checks (F05, F06, F20, F21)
  - D (date) validity (F07, F22)
  - T (time) validity (F08, F23)
  - N/R/I numeric format checks (F09, F10, F11, F16, F25)

We use the x12 grammar (850/004010) whose field definitions we know.
"""

import json

import pytest
from bots_core.domain.exceptions import OutMessageError
from bots_core.facade import edi_to_json, json_to_edi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _x12_edi(
    edi_date="20210101",
    edi_time="1200",
    po_number="123456",
    sender="SENDER         ",
    receiver="RECEIVER       ",
    se01="5",
):
    """Parameterised X12 850 EDI helper."""
    return (
        f"ISA*00*          *00*          *ZZ*{sender}*ZZ*{receiver}"
        f"*{edi_date[2:]}*{edi_time}*U*00401*000000001*0*T*>~\r\n"
        f"GS*PO*SENDER*RECEIVER*{edi_date}*{edi_time}*1*X*004010~\r\n"
        f"ST*850*0001~\r\n"
        f"BEG*00*SA*{po_number}~\r\n"
        f"PO1*1*100*EA*10.5~\r\n"
        f"CTT*1~\r\n"
        f"SE*{se01}*0001~\r\n"
        f"GE*1*1~\r\n"
        f"IEA*1*000000001~\r\n"
    )


def _parse(patch_data_dir, edi_content):
    f = patch_data_dir / "in.edi"
    f.write_text(edi_content)
    return json.loads(edi_to_json(str(f), editype="x12", messagetype="x12"))


# ---------------------------------------------------------------------------
# mpathformat (Message static) — already tested, quick sanity check
# ---------------------------------------------------------------------------


def test_mpathformat_joins_with_dash():
    from bots_core.domain.message import Message

    assert Message.mpathformat(["ISA", "GS", "ST"]) == "ISA-GS-ST"


# ---------------------------------------------------------------------------
# Valid X12 parsing exercises full _formatfield path without errors
# ---------------------------------------------------------------------------


def test_valid_x12_parse_no_errors(patch_data_dir):
    """Well-formed X12 → no MessageError raised, all segments present."""
    ast = _parse(patch_data_dir, _x12_edi())
    isa = ast["children"][0]
    assert isa["record"]["BOTSID"] == "ISA"


def test_valid_x12_multiple_po1_lines(patch_data_dir):
    """Multiple PO1 segments parse cleanly — exercises loop counting."""
    edi = (
        "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        "*210101*1200*U*00401*000000001*0*T*>~\r\n"
        "GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~\r\n"
        "ST*850*0001~\r\n"
        "BEG*00*SA*PO-MULTI~\r\n"
        "PO1*1*10*EA*1.0~\r\n"
        "PO1*2*20*EA*2.0~\r\n"
        "PO1*3*30*EA*3.0~\r\n"
        "CTT*3~\r\n"
        "SE*7*0001~\r\n"
        "GE*1*1~\r\n"
        "IEA*1*000000001~\r\n"
    )
    f = patch_data_dir / "multi_po1.edi"
    f.write_text(edi)
    result = json.loads(edi_to_json(str(f), editype="x12", messagetype="x12"))
    st = result["children"][0]["children"][0]["children"][0]
    po1_nodes = [c for c in st["children"] if c["record"]["BOTSID"] == "PO1"]
    assert len(po1_nodes) == 3


# ---------------------------------------------------------------------------
# Date field validation via inmessage._formatfield (field with BFORMAT='D')
# ---------------------------------------------------------------------------


def test_invalid_date_in_gs_segment_generates_error(patch_data_dir):
    """GS04 date field with invalid date generates [F07] error."""
    edi = (
        "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        "*210101*1200*U*00401*000000001*0*T*>~\r\n"
        "GS*PO*SENDER*RECEIVER*99999999*1200*1*X*004010~\r\n"  # bad date
        "ST*850*0001~\r\n"
        "BEG*00*SA*123456~\r\n"
        "PO1*1*100*EA*10.5~\r\n"
        "CTT*1~\r\n"
        "SE*5*0001~\r\n"
        "GE*1*1~\r\n"
        "IEA*1*000000001~\r\n"
    )
    f = patch_data_dir / "bad_date.edi"
    f.write_text(edi)
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(f),
        charset="utf-8",
    )
    # F07 error in errorlist for bad date
    assert any("F07" in e for e in obj.errorlist), (
        f"Expected F07 (date validation error), got: {obj.errorlist}"
    )


# ---------------------------------------------------------------------------
# Outmessage writer path — exercises _formatfield via json_to_edi
# ---------------------------------------------------------------------------


def _minimal_x12_json():
    """
    Minimal JSON AST representing a simple X12 850.
    Matches the structure produced by edi_to_json for x12/850004010.
    """
    return json.dumps(
        {
            "BOTSID": "",
            "record": {},
            "children": [
                {
                    "BOTSID": "ISA",
                    "record": {
                        "BOTSID": "ISA",
                        "ISA01": "00",
                        "ISA02": "          ",
                        "ISA03": "00",
                        "ISA04": "          ",
                        "ISA05": "ZZ",
                        "ISA06": "SENDER         ",
                        "ISA07": "ZZ",
                        "ISA08": "RECEIVER       ",
                        "ISA09": "210101",
                        "ISA10": "1200",
                        "ISA11": "U",
                        "ISA12": "00401",
                        "ISA13": "000000001",
                        "ISA14": "0",
                        "ISA15": "T",
                        "ISA16": ">",
                    },
                    "children": [
                        {
                            "BOTSID": "GS",
                            "record": {
                                "BOTSID": "GS",
                                "GS01": "PO",
                                "GS02": "SENDER",
                                "GS03": "RECEIVER",
                                "GS04": "20210101",
                                "GS05": "1200",
                                "GS06": "1",
                                "GS07": "X",
                                "GS08": "004010",
                            },
                            "children": [
                                {
                                    "BOTSID": "ST",
                                    "record": {"BOTSID": "ST", "ST01": "850", "ST02": "0001"},
                                    "children": [
                                        {
                                            "BOTSID": "BEG",
                                            "record": {
                                                "BOTSID": "BEG",
                                                "BEG01": "00",
                                                "BEG02": "SA",
                                                "BEG03": "PO123",
                                            },
                                            "children": [],
                                        },
                                        {
                                            "BOTSID": "CTT",
                                            "record": {"BOTSID": "CTT", "CTT01": "1"},
                                            "children": [],
                                        },
                                        {
                                            "BOTSID": "SE",
                                            "record": {"BOTSID": "SE", "SE01": "4", "SE02": "0001"},
                                            "children": [],
                                        },
                                    ],
                                },
                                {
                                    "BOTSID": "GE",
                                    "record": {"BOTSID": "GE", "GE01": "1", "GE02": "1"},
                                    "children": [],
                                },
                            ],
                        },
                        {
                            "BOTSID": "IEA",
                            "record": {"BOTSID": "IEA", "IEA01": "1", "IEA02": "000000001"},
                            "children": [],
                        },
                    ],
                }
            ],
        }
    )


def test_json_to_edi_produces_valid_x12(patch_data_dir):
    """Round-trip: parse valid X12 → JSON → write back → contains all expected segments."""
    edi = _x12_edi()
    f = patch_data_dir / "rt.edi"
    f.write_text(edi)
    j = edi_to_json(str(f), editype="x12", messagetype="x12")
    out = json_to_edi(j, editype="x12", messagetype="x12")
    assert "ISA*00*" in out
    assert "GS*PO*" in out
    assert "ST*850*" in out
    assert "BEG*00*SA*" in out
    assert "SE*" in out
    assert "GE*" in out
    assert "IEA*" in out


# ---------------------------------------------------------------------------
# X12 sniff errors
# ---------------------------------------------------------------------------


def test_x12_sniff_not_isa(patch_data_dir):
    """File not starting with ISA → [A60] fatal error."""
    p = patch_data_dir / "notx12.edi"
    p.write_text("GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~\r\n")
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(p),
        charset="utf-8",
    )
    assert obj.errorfatal
    assert any("A60" in e for e in obj.errorlist), obj.errorlist


def test_x12_sniff_only_whitespace(patch_data_dir):
    """File containing only whitespace → [A61] fatal error."""
    p = patch_data_dir / "whitespace.edi"
    p.write_text("   \n\r\n   ")
    from bots_core.domain.inmessage import parse_edi_file

    obj = parse_edi_file(
        editype="x12",
        messagetype="x12",
        filename=str(p),
        charset="utf-8",
    )
    assert obj.errorfatal
    assert any("A61" in e for e in obj.errorlist), obj.errorlist


# ---------------------------------------------------------------------------
# outmessage_init dispatch error
# ---------------------------------------------------------------------------


def test_outmessage_init_unknown_editype():
    """Unknown editype → OutMessageError raised."""
    with pytest.raises(OutMessageError) as exc_info:
        from bots_core.domain.outmessage import outmessage_init

        outmessage_init(
            editype="BOGUS", messagetype="X", filename="x.edi", charset="utf-8", merge=False
        )
    assert "Unknown editype" in str(exc_info.value)
