"""
test_grammar_advanced.py
Extended test suite for grammar.py covering previously uncovered branches such as:
- missing recorddefs (GrammarPartMissing)
- ERROR_IN_GRAMMAR flags
- invalid fields (ID not string, MANDATORY invalid, MINLENGTH vs LENGTH, FORMAT not string, etc.)
"""

import pytest

from edi.core.bots.config.botsconfig import (
    BFORMAT,
    DECIMALS,
    LENGTH,
    MANDATORY,
    MAXREPEAT,
)
from edi.core.bots.domain.exceptions import BotsImportError, GrammarError, GrammarPartMissing
from edi.core.bots.domain.grammar import loader, validator
from edi.core.bots.domain.grammar.grammar import ERROR_IN_GRAMMAR, Grammar
from edi.core.bots.domain.grammar.loader import grammarread, init_restofgrammar


class MockGrammar(Grammar):
    def __init__(self, typeofgrammarfile, editype, grammarname):
        self.typeofgrammarfile = typeofgrammarfile
        self.editype = editype
        self.grammarname = grammarname
        self.recorddefs = {}
        self.structure = []
        self.syntax = {}

        class MockModule:
            pass

        self.module = MockModule()

    def _manipulatefieldformat(self, field, recordid):
        pass


def test_dorecorddefs_missing_recorddefs():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    del g.recorddefs
    with pytest.raises(GrammarPartMissing) as exc_info:
        loader.do_recorddefs(g)
    assert "no recorddefs" in str(exc_info.value)


def test_dorecorddefs_not_dict():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    g.module.recorddefs = []
    with pytest.raises(GrammarPartMissing) as exc_info:
        loader.do_recorddefs(g)
    assert "not a dict" in str(exc_info.value)


def test_dorecorddefs_already_errored():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    g.module.recorddefs = {ERROR_IN_GRAMMAR: True}
    with pytest.raises(GrammarError) as exc_info:
        loader.do_recorddefs(g)
    assert "already reported" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# _checkfield checks
# ---------------------------------------------------------------------------


def test_checkfield_invalid_id():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = [123, "C", 10, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "fieldID has to be a string" in str(exc_info.value)


def test_checkfield_invalid_mandatory_string():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "X", 10, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "mandatory/conditional must be" in str(exc_info.value)


def test_checkfield_invalid_mandatory_tuple():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", ("X", 5), 10, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "mandatory/conditional must be" in str(exc_info.value)


def test_checkfield_invalid_mandatory_tuple_type():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", (1, 5), 10, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "mandatory/conditional must be" in str(exc_info.value)


def test_checkfield_invalid_mandatory_repeats_not_int():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", ("C", "many"), 10, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "number of repeats must be integer" in str(exc_info.value)


def test_checkfield_mandatory_tuple_correct():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", ("C", 5), 10, "AN"]
    validator.checkfield(g, field, "REC1")
    assert field[MAXREPEAT] == 5
    assert field[MANDATORY] == 0


def test_checkfield_invalid_mandatory_type():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", 123, 10, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "mandatory/conditional has to be a string" in str(exc_info.value)


def test_checkfield_invalid_length_tuple():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", ("1", 10), "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "min length" in str(exc_info.value) and "has to be a number" in str(exc_info.value)


def test_checkfield_invalid_max_length_tuple():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", (1, "10"), "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "max length" in str(exc_info.value) and "has to be a number" in str(exc_info.value)


def test_checkfield_min_gt_max_length():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", (10, 5), "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "min length" in str(exc_info.value) and "must be > max length" in str(exc_info.value)


def test_checkfield_invalid_length_type():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", "10", "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "has to be number or (min,max)" in str(exc_info.value)


def test_checkfield_length_too_small():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", 0, "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "at least 1" in str(exc_info.value)


def test_checkfield_minlength_negative():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", (-1, 10), "AN"]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "minlength" in str(exc_info.value) and "at least 0" in str(exc_info.value)


def test_checkfield_invalid_format_type():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", 10, 123]
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "format" in str(exc_info.value) and "has to be a string" in str(exc_info.value)


def test_checkfield_numeric_float_length():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", 10.5, "R"]

    # _manipulatefieldformat is mocked in this test to not set BFORMAT
    # But BFORMAT is used to check float length. We must set it manually.
    def mock_manipulatefieldformat(f, r):
        f[BFORMAT] = "R"

    g._manipulatefieldformat = mock_manipulatefieldformat
    validator.checkfield(g, field, "REC1")
    assert field[DECIMALS] == 5
    assert field[LENGTH] == 10


def test_checkfield_numeric_float_length_invalid():
    g = MockGrammar("grammars", "mock_edi", "mock_grammar")
    field = ["FLD1", "M", 2.3, "R"]

    def mock_manipulatefieldformat(f, r):
        f[BFORMAT] = "R"

    g._manipulatefieldformat = mock_manipulatefieldformat
    with pytest.raises(GrammarError) as exc_info:
        validator.checkfield(g, field, "REC1")
    assert "field length" in str(exc_info.value) and "greater that nr of decimals" in str(
        exc_info.value
    )


# ---------------------------------------------------------
# Tests for loader.grammarread and loader.init_restofgrammar
# ---------------------------------------------------------


class MockGrammarModule:
    def __init__(self):
        self.syntax = {"has_structure": False, "envelope": "mock_env"}
        self.recorddefs = {}
        self.structure = []


class MockEnvModule:
    def __init__(self):
        self.syntax = {"has_structure": False}
        self.recorddefs = {}
        self.structure = []


def mock_botsimport(typeofgrammarfile, editype, grammarname):
    if grammarname == "mock_grammar":
        return MockGrammarModule(), grammarname
    elif grammarname == "mock_env":
        return MockEnvModule(), grammarname
    elif grammarname == "raise_env":
        raise BotsImportError("test")
    else:
        raise BotsImportError(f"Unknown {grammarname}")


def test_grammar_read_envelope(monkeypatch):
    import edi.core.bots.utils.botslib as botslib

    monkeypatch.setattr(botslib, "botsimport", mock_botsimport)

    env_grammar = grammarread("test", "mock_grammar", "envelope")
    assert env_grammar.grammarname == "mock_env"


def test_grammar_read_envelope_import_error(monkeypatch):
    import edi.core.bots.utils.botslib as botslib

    def mock_botsimport_err(typeofgrammarfile, editype, grammarname):
        if grammarname == "mock_grammar":
            mod = MockGrammarModule()
            mod.syntax["envelope"] = "raise_env"
            return mod, grammarname
        elif grammarname == "raise_env":
            raise BotsImportError("test")
        else:
            raise BotsImportError(f"Unknown {grammarname}")

    monkeypatch.setattr(botslib, "botsimport", mock_botsimport_err)

    env_grammar = grammarread("test", "mock_grammar", "envelope")
    assert env_grammar.grammarname == "mock_grammar"


def test_grammar_read_partners(monkeypatch):
    import edi.core.bots.utils.botslib as botslib

    monkeypatch.setattr(botslib, "botsimport", mock_botsimport)
    part_grammar = grammarread("test", "mock_grammar", "partners")
    assert part_grammar.grammarname == "mock_grammar"
    assert part_grammar.syntax is not part_grammar.original_syntaxfromgrammar


def test_grammar_read_unknown_type(monkeypatch):
    import edi.core.bots.utils.botslib as botslib

    monkeypatch.setattr(botslib, "botsimport", mock_botsimport)
    with pytest.raises(BotsImportError, match="Unknown typeofgrammarfile"):
        grammarread("test", "mock_grammar", "unknown_type")


def test_init_restofgrammar_nextmessage_logic():
    class TestGrammar:
        grammarname = "test"

        class module:
            nextmessage = None
            nextmessage2 = "msg2"
            nextmessageblock = None

        syntax = {"has_structure": False}

    with pytest.raises(GrammarError, match="if nextmessage2: nextmessage has to be used"):
        init_restofgrammar(TestGrammar())


def test_init_restofgrammar_nextmessageblock_logic():
    class TestGrammar:
        grammarname = "test"

        class module:
            nextmessage = "msg"
            nextmessage2 = None
            nextmessageblock = "block"

        syntax = {"has_structure": False}

    with pytest.raises(GrammarError, match="nextmessageblock and nextmessage not both allowed"):
        init_restofgrammar(TestGrammar())
