"""
test_edifact_parsing.py
Tests for EDIFACT-specific business logic:
- _sniff error paths (BOM, missing UNB, UNA errors)
- checkenvelope (E01-E12: reference mismatches, count mismatches)
- Correct round-trip parsing

These cover the heavily-uncovered paths in parsers/edifact.py.
"""

import pytest
from bots_core.domain.exceptions import InMessageError
from bots_core.domain.inmessage import parse_edi_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_edifact(
    unb_ref="1",
    unz_ref="1",
    unz_count="1",
    unh_ref="1",
    unt_ref="1",
    unt_count="4",
    charset="utf8",
):
    """
    Build a minimal EDIFACT ORDERS message using utf8 charset.
    UNT count = UNH + BGM + DTM + UNT = 4 segments.
    """
    return (
        f"UNA:+.? '\n"
        f"UNB+{charset}:1+SENDER+RECEIVER+210101:1200+{unb_ref}'\n"
        f"UNH+{unh_ref}+ORDERS:D:96A:UN'\n"
        f"BGM+220+PO123+9'\n"
        f"DTM+137:20210101:102'\n"
        f"UNT+{unt_count}+{unt_ref}'\n"
        f"UNZ+{unz_count}+{unz_ref}'\n"
    )


def _write(patch_data_dir, content, filename="test.edi"):
    p = patch_data_dir / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def _parse(path, patch_data_dir):
    return parse_edi_file(
        editype="edifact",
        messagetype="edifact",
        filename=path,
        charset="utf-8",
    )


# ---------------------------------------------------------------------------
# _sniff error paths
# ---------------------------------------------------------------------------


def test_sniff_bom_raises(patch_data_dir):
    """UTF-8 BOM at start → [A68] error."""
    content = b"\xef\xbb\xbfUNB+utf8:1+S+R+210101:1200+1'\n"
    p = patch_data_dir / "bom.edi"
    p.write_bytes(content)
    obj = parse_edi_file(
        editype="edifact",
        messagetype="edifact",
        filename=str(p),
        charset="utf-8",
    )
    assert obj.errorfatal
    assert any("A68" in e for e in obj.errorlist), obj.errorlist


def test_sniff_missing_unb_raises(patch_data_dir):
    """File that starts with random text → [A54] error."""
    p = _write(patch_data_dir, "NOTEDI+GARBAGE'\n")
    obj = _parse(p, patch_data_dir)
    assert obj.errorfatal
    assert any("A54" in e for e in obj.errorlist), obj.errorlist


def test_sniff_una_then_garbage(patch_data_dir):
    """UNA present but truncated → [A53] error."""
    # UNA needs 6 chars after 'UNA'; give only 2
    content = b"UNA:+"
    p = patch_data_dir / "una_trunc.edi"
    p.write_bytes(content)
    obj = parse_edi_file(
        editype="edifact",
        messagetype="edifact",
        filename=str(p),
        charset="utf-8",
    )
    assert obj.errorfatal
    assert any("A53" in e for e in obj.errorlist), obj.errorlist


# ---------------------------------------------------------------------------
# checkenvelope — reference mismatches and count errors
# ---------------------------------------------------------------------------


def test_edifact_correct_envelope_no_errors(patch_data_dir):
    """Perfectly formed EDIFACT → no envelope errors (E0x)."""
    p = _write(patch_data_dir, _basic_edifact())
    obj = _parse(p, patch_data_dir)
    env_errors = [e for e in obj.errorlist if "[E" in e]
    assert env_errors == [], f"Unexpected envelope errors: {env_errors}"


def test_edifact_unb_unz_reference_mismatch(patch_data_dir):
    """UNB ref ≠ UNZ ref → [E01]."""
    p = _write(patch_data_dir, _basic_edifact(unb_ref="111", unz_ref="999"))
    obj = _parse(p, patch_data_dir)
    assert any("E01" in e for e in obj.errorlist), obj.errorlist


def test_edifact_unz_count_too_high(patch_data_dir):
    """UNZ says 5 messages but only 1 → [E02]."""
    p = _write(patch_data_dir, _basic_edifact(unz_count="5"))
    obj = _parse(p, patch_data_dir)
    assert any("E02" in e for e in obj.errorlist), obj.errorlist


def test_edifact_unz_count_non_numeric(patch_data_dir):
    """UNZ count = 'X' (non-numeric) → [E03]."""
    content = (
        "UNA:+.? '\n"
        "UNB+utf8:1+SENDER+RECEIVER+210101:1200+1'\n"
        "UNH+1+ORDERS:D:96A:UN'\n"
        "BGM+220+PO123+9'\n"
        "DTM+137:20210101:102'\n"
        "UNT+4+1'\n"
        "UNZ+X+1'\n"
    )
    p = _write(patch_data_dir, content)
    obj = _parse(p, patch_data_dir)
    assert any("E03" in e for e in obj.errorlist), obj.errorlist


def test_edifact_unh_unt_reference_mismatch(patch_data_dir):
    """UNH ref ≠ UNT ref → [E04]."""
    p = _write(patch_data_dir, _basic_edifact(unh_ref="AAA", unt_ref="ZZZ"))
    obj = _parse(p, patch_data_dir)
    assert any("E04" in e for e in obj.errorlist), obj.errorlist


def test_edifact_unt_segment_count_too_high(patch_data_dir):
    """UNT count says 99 but actual is 4 → [E05]."""
    p = _write(patch_data_dir, _basic_edifact(unt_count="99"))
    obj = _parse(p, patch_data_dir)
    assert any("E05" in e for e in obj.errorlist), obj.errorlist


def test_edifact_unt_count_non_numeric(patch_data_dir):
    """UNT count = 'Z' → [E06]."""
    content = (
        "UNA:+.? '\n"
        "UNB+utf8:1+SENDER+RECEIVER+210101:1200+1'\n"
        "UNH+1+ORDERS:D:96A:UN'\n"
        "BGM+220+PO123+9'\n"
        "DTM+137:20210101:102'\n"
        "UNT+Z+1'\n"
        "UNZ+1+1'\n"
    )
    p = _write(patch_data_dir, content)
    obj = _parse(p, patch_data_dir)
    assert any("E06" in e for e in obj.errorlist), obj.errorlist


# ---------------------------------------------------------------------------
# parse_edi_file dispatch error
# ---------------------------------------------------------------------------


def test_unknown_editype_raises(patch_data_dir):
    """Requesting unknown editype → InMessageError raised immediately."""
    p = _write(patch_data_dir, "dummy")
    with pytest.raises(InMessageError) as exc_info:
        parse_edi_file(
            editype="UNKNOWN_FORMAT",
            messagetype="X",
            filename=p,
            charset="utf-8",
        )
    assert "Unknown editype" in str(exc_info.value)


# ---------------------------------------------------------------------------
# set_syntax_used (edifact stores separators in self.syntax)
# ---------------------------------------------------------------------------


def test_edifact_syntax_separators_stored(patch_data_dir):
    """After parsing, edifact.syntax captures the actual separators used."""
    p = _write(patch_data_dir, _basic_edifact())
    obj = _parse(p, patch_data_dir)
    assert obj.syntax.get("record_sep") == "'"
    assert obj.syntax.get("field_sep") == "+"
    assert obj.syntax.get("sfield_sep") == ":"
    assert obj.syntax.get("record_tag_sep", "") == ""
