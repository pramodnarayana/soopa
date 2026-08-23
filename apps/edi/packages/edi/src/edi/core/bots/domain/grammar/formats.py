"""
grammar subclasses. contain the defaultsyntax and format conversions.
"""

from edi.core.bots.config.botsconfig import BFORMAT, DECIMALS, FORMAT
from edi.core.bots.domain.grammar.grammar import Grammar


class test(Grammar):
    """For unit tests"""

    defaultsyntax = {
        "has_structure": True,  # is True, read structure, recorddef, check these
        "checkcollision": True,
        "noBOTSID": False,
        "preprocess_lex": False,
        "preprocess_nodes": False,
    }
    formatconvert = {"A": "A", "AN": "A", "N": "R"}


class edifact(Grammar):
    defaultsyntax = {
        "add_crlfafterrecord_sep": "\r\n",
        "charset": "UNOA",
        "checkcharsetin": "strict",
        "checkcharsetout": "strict",
        "contenttype": "application/EDIFACT",
        "decimaal": ".",
        "envelope": "edifact",
        "escape": "?",
        "field_sep": "+",
        "forceUNA": False,
        "merge": True,
        "record_sep": "'",
        "reserve": "*",
        "sfield_sep": ":",
        "skip_char": "\r\n",
        "strict_syntax_check": False,
        "strip_value": False,
        "version": "3",
        "UNB.S001.0080": "",
        "UNB.S001.0133": "",
        "UNB.S002.0007": "14",
        "UNB.S002.0008": "",
        "UNB.S002.0042": "",
        "UNB.S003.0007": "14",
        "UNB.S003.0014": "",
        "UNB.S003.0046": "",
        "UNB.S005.0022": "",
        "UNB.S005.0025": "",
        "UNB.0026": "",
        "UNB.0029": "",
        "UNB.0031": "",
        "UNB.0032": "",
        "UNB.0035": "0",
        "checkunknownentities": True,
        "forcequote": 0,
        "preprocess_lex": False,
        "preprocess_nodes": False,
        "quote_char": "",
        "record_tag_sep": "",
        "triad": "",
        "has_structure": True,
        "checkcollision": True,
        "lengthnumericbare": True,
        "stripfield_sep": True,
    }
    formatconvert = {"A": "A", "AN": "A", "N": "R"}


class x12(Grammar):
    defaultsyntax = {
        "add_crlfafterrecord_sep": "\r\n",
        "charset": "us-ascii",
        "checkcharsetin": "strict",
        "checkcharsetout": "strict",
        "contenttype": "application/X12",
        "decimaal": ".",
        "envelope": "x12",
        "escape": "",
        "field_sep": "*",
        "functionalgroup": "XX",
        "merge": True,
        "record_sep": "~",
        "replacechar": "",
        "reserve": "^",
        "sfield_sep": ">",
        "skip_char": "\r\n",
        "strict_syntax_check": False,
        "strip_value": False,
        "version": "00403",
        "ISA01": "00",
        "ISA02": "          ",
        "ISA03": "00",
        "ISA04": "          ",
        "ISA05": "01",
        "ISA07": "01",
        "ISA11": "U",
        "ISA14": "0",
        "ISA15": "P",
        "GS07": "X",
        "checkunknownentities": True,
        "forcequote": 0,
        "preprocess_lex": False,
        "preprocess_nodes": False,
        "quote_char": "",
        "record_tag_sep": "",
        "triad": "",
        "has_structure": True,
        "checkcollision": True,
        "lengthnumericbare": True,
        "stripfield_sep": True,
    }
    formatconvert = {
        "AN": "A",
        "DT": "D",
        "TM": "T",
        "N": "I",
        "N0": "I",
        "N1": "I",
        "N2": "I",
        "N3": "I",
        "N4": "I",
        "N5": "I",
        "N6": "I",
        "N7": "I",
        "N8": "I",
        "N9": "I",
        "R": "R",
        "B": "A",
        "ID": "A",
    }

    def _manipulatefieldformat(self, field, recordid):
        super()._manipulatefieldformat(field, recordid)
        if field[BFORMAT] == "I":
            if field[FORMAT][1:]:
                field[DECIMALS] = int(field[FORMAT][1])
            else:
                field[DECIMALS] = 0
