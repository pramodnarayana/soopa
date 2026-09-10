from pathlib import Path

import pytest

from edi.core.bots.domain.grammar import grammarcheck


def test_startmulti_checks_every_grammar_before_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for filename in ("valid.py", "invalid.py", "also_valid.py"):
        (tmp_path / filename).touch()

    checked_grammars: list[str] = []

    def fake_grammarread(editype: str, messagetype: str, typeofgrammarfile: str) -> None:
        checked_grammars.append(messagetype)
        if messagetype == "invalid":
            raise ValueError("invalid grammar")

    monkeypatch.setattr(grammarcheck.grammar, "grammarread", fake_grammarread)

    with pytest.raises(SystemExit) as exc_info:
        grammarcheck.startmulti(str(tmp_path), "x12")

    assert exc_info.value.code == 1
    assert set(checked_grammars) == {"valid", "invalid", "also_valid"}


def test_startmulti_completes_when_all_grammars_are_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "valid.py").touch()
    checked_grammars: list[str] = []

    def fake_grammarread(editype: str, messagetype: str, typeofgrammarfile: str) -> None:
        checked_grammars.append(messagetype)

    monkeypatch.setattr(grammarcheck.grammar, "grammarread", fake_grammarread)

    grammarcheck.startmulti(str(tmp_path), "x12")

    assert checked_grammars == ["valid"]
