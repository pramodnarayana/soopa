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
from bots_core.utils.botslib import botsglobal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_data_dir(tmp_path):
    orig = botsglobal.ini.get

    def patched(section, key, fallback=""):
        if section == "directories" and key == "data":
            return str(tmp_path)
        return fallback

    botsglobal.ini.get = patched
    return orig


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


def _write(tmp_path, content, filename="test.edi"):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def _parse(path, tmp_path):
    return parse_edi_file(
        editype="edifact",
        messagetype="edifact",
        filename=path,
        charset="utf-8",
    )


# ---------------------------------------------------------------------------
# _sniff error paths
# ---------------------------------------------------------------------------


def test_sniff_bom_raises(tmp_path):
    """UTF-8 BOM at start → [A68] error."""
    content = b"\xef\xbb\xbfUNB+utf8:1+S+R+210101:1200+1'\n"
    p = tmp_path / "bom.edi"
    p.write_bytes(content)
    orig = _patch_data_dir(tmp_path)
    try:
        obj = parse_edi_file(
            editype="edifact",
            messagetype="edifact",
            filename=str(p),
            charset="utf-8",
        )
        assert obj.errorfatal
        assert any("A68" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_sniff_missing_unb_raises(tmp_path):
    """File that starts with random text → [A54] error."""
    p = _write(tmp_path, "NOTEDI+GARBAGE'\n")
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert obj.errorfatal
        assert any("A54" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_sniff_una_then_garbage(tmp_path):
    """UNA present but truncated → [A53] error."""
    # UNA needs 6 chars after 'UNA'; give only 2
    content = b"UNA:+"
    p = tmp_path / "una_trunc.edi"
    p.write_bytes(content)
    orig = _patch_data_dir(tmp_path)
    try:
        obj = parse_edi_file(
            editype="edifact",
            messagetype="edifact",
            filename=str(p),
            charset="utf-8",
        )
        assert obj.errorfatal
        assert any("A53" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


# ---------------------------------------------------------------------------
# checkenvelope — reference mismatches and count errors
# ---------------------------------------------------------------------------


def test_edifact_correct_envelope_no_errors(tmp_path):
    """Perfectly formed EDIFACT → no envelope errors (E0x)."""
    p = _write(tmp_path, _basic_edifact())
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        env_errors = [e for e in obj.errorlist if "[E" in e]
        assert env_errors == [], f"Unexpected envelope errors: {env_errors}"
    finally:
        botsglobal.ini.get = orig


def test_edifact_unb_unz_reference_mismatch(tmp_path):
    """UNB ref ≠ UNZ ref → [E01]."""
    p = _write(tmp_path, _basic_edifact(unb_ref="111", unz_ref="999"))
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert any("E01" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_edifact_unz_count_too_high(tmp_path):
    """UNZ says 5 messages but only 1 → [E02]."""
    p = _write(tmp_path, _basic_edifact(unz_count="5"))
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert any("E02" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_edifact_unz_count_non_numeric(tmp_path):
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
    p = _write(tmp_path, content)
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert any("E03" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_edifact_unh_unt_reference_mismatch(tmp_path):
    """UNH ref ≠ UNT ref → [E04]."""
    p = _write(tmp_path, _basic_edifact(unh_ref="AAA", unt_ref="ZZZ"))
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert any("E04" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_edifact_unt_segment_count_too_high(tmp_path):
    """UNT count says 99 but actual is 4 → [E05]."""
    p = _write(tmp_path, _basic_edifact(unt_count="99"))
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert any("E05" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


def test_edifact_unt_count_non_numeric(tmp_path):
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
    p = _write(tmp_path, content)
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        assert any("E06" in e for e in obj.errorlist), obj.errorlist
    finally:
        botsglobal.ini.get = orig


# ---------------------------------------------------------------------------
# parse_edi_file dispatch error
# ---------------------------------------------------------------------------


def test_unknown_editype_raises(tmp_path):
    """Requesting unknown editype → InMessageError raised immediately."""
    p = _write(tmp_path, "dummy")
    orig = _patch_data_dir(tmp_path)
    try:
        with pytest.raises(InMessageError) as exc_info:
            parse_edi_file(
                editype="UNKNOWN_FORMAT",
                messagetype="X",
                filename=p,
                charset="utf-8",
            )
        assert "Unknown editype" in str(exc_info.value)
    finally:
        botsglobal.ini.get = orig


# ---------------------------------------------------------------------------
# set_syntax_used (edifact stores separators in self.syntax)
# ---------------------------------------------------------------------------


def test_edifact_syntax_separators_stored(tmp_path):
    """After parsing, edifact.syntax captures the actual separators used."""
    p = _write(tmp_path, _basic_edifact())
    orig = _patch_data_dir(tmp_path)
    try:
        obj = _parse(p, tmp_path)
        # These are set in edifact.set_syntax_used()
        for key in ("record_sep", "field_sep", "sfield_sep"):
            assert key in obj.syntax, f"Missing key {key!r} in obj.syntax"
    finally:
        botsglobal.ini.get = orig
