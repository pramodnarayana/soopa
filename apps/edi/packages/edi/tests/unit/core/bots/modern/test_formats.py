from edi.core.bots.config.botsconfig import BFORMAT, DECIMALS, FORMAT, ID
from edi.core.bots.domain.grammar.formats import x12

"""
Tests for bots_core.domain.grammar.formats
"""


def test_formats_edifact_decimals_no_suffix():
    """
    formats.py line 142: when BFORMAT == 'I' and FORMAT has no digit suffix,
    DECIMALS should be set to 0.
    """

    g = object.__new__(x12)
    g.grammarname = "test"
    # x12.formatconvert maps "N" -> "I"
    g.formatconvert = {"N": "I", "AN": "A"}

    field = {ID: "QTY01", FORMAT: "N", BFORMAT: "I", DECIMALS: None}
    # Call the parent _manipulatefieldformat first to set BFORMAT, then edifact override
    # Simulate a field where BFORMAT is already "I" and FORMAT has no digit suffix (just "N")
    g._manipulatefieldformat(field, "QTY")
    assert field[DECIMALS] == 0


def test_formats_edifact_decimals_with_suffix():
    """
    formats.py line 140: when BFORMAT == 'I' and FORMAT has a digit suffix,
    DECIMALS should be set to that digit.
    """

    g = object.__new__(x12)
    g.grammarname = "test"
    g.formatconvert = {"N3": "I", "AN": "A"}

    field = {ID: "AMT01", FORMAT: "N3", BFORMAT: "I", DECIMALS: None}
    g._manipulatefieldformat(field, "AMT")
    assert field[DECIMALS] == 3
