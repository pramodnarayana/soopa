"""Architectural unit tests enforcing Single Responsibility Principle (SRP) naming conventions across IP test suites."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

_CONJOINED_PY_FUNC_PATTERN = re.compile(r"^test_.*_and_.*$")
_CONJOINED_PY_CLASS_PATTERN = re.compile(r"^Test.*[a-z0-9]And[A-Z].*$")
_CONJOINED_FILENAME_PATTERN = re.compile(r"(?:_and_|-and-)", re.IGNORECASE)
_VITEST_BLOCK_TITLE_PATTERN = re.compile(
    r"\b(?:describe|it|test)\s*\(\s*(?P<quote>['\"`])(?P<title>(?:\\.|(?!(?P=quote)).)*?)(?P=quote)",
    re.DOTALL,
)
_CONJOINED_UI_TITLE_PATTERN = re.compile(r"(?:\band\b|&)", re.IGNORECASE)


def _ip_pkg_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[7]


def test_ip_test_filenames_exclude_conjoined_tokens() -> None:
    py_tests_dir = _ip_pkg_root() / "tests"
    ui_tests_dir = _repo_root() / "apps" / "ip" / "packages" / "ui" / "src" / "__tests__"

    offenders: list[str] = []
    for py_file in sorted(py_tests_dir.rglob("*.py")):
        if _CONJOINED_FILENAME_PATTERN.search(py_file.name) is not None:
            offenders.append(str(py_file.relative_to(_repo_root())))

    for ui_file in sorted(ui_tests_dir.rglob("*")):
        if ui_file.suffix not in {".ts", ".tsx"}:
            continue
        if _CONJOINED_FILENAME_PATTERN.search(ui_file.name) is not None:
            offenders.append(str(ui_file.relative_to(_repo_root())))

    assert offenders == []


def test_ip_python_tests_exclude_conjoined_function_or_class_names() -> None:
    py_tests_dir = _ip_pkg_root() / "tests"
    offenders: list[str] = []

    for py_file in sorted(py_tests_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _CONJOINED_PY_FUNC_PATTERN.match(node.name) is not None
            ) or (
                isinstance(node, ast.ClassDef)
                and _CONJOINED_PY_CLASS_PATTERN.match(node.name) is not None
            ):
                rel = py_file.relative_to(py_tests_dir)
                offenders.append(f"{rel}:{node.lineno} -> {node.name}")

    assert offenders == []


def test_ip_ui_tests_exclude_conjoined_titles() -> None:
    ui_tests_dir = _repo_root() / "apps" / "ip" / "packages" / "ui" / "src" / "__tests__"
    offenders: list[str] = []

    for ui_file in sorted(ui_tests_dir.rglob("*")):
        if ui_file.suffix not in {".ts", ".tsx"}:
            continue
        text = ui_file.read_text(encoding="utf-8")
        for match in _VITEST_BLOCK_TITLE_PATTERN.finditer(text):
            title = match.group("title")
            if _CONJOINED_UI_TITLE_PATTERN.search(title) is not None:
                rel = ui_file.relative_to(ui_tests_dir)
                offenders.append(f"{rel}: {title}")

    assert offenders == []


def test_srp_class_pattern_detects_conjoined_class_names() -> None:
    assert _CONJOINED_PY_CLASS_PATTERN.match("TestCreateAndDeleteConnection") is not None
    assert _CONJOINED_PY_CLASS_PATTERN.match("TestAndroidWebhookVerifier") is None


def test_srp_title_pattern_detects_template_literal_titles() -> None:
    sample_ts = "it(`creates connection and triggers sync`, async () => {});"
    matches = [m.group("title") for m in _VITEST_BLOCK_TITLE_PATTERN.finditer(sample_ts)]
    assert matches == ["creates connection and triggers sync"]
    assert _CONJOINED_UI_TITLE_PATTERN.search(matches[0]) is not None


def test_semgrep_architecture_config_defines_srp_rules() -> None:
    semgrep_path = _repo_root() / "semgrep-architecture.yml"
    parsed = yaml.safe_load(semgrep_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    rules = parsed.get("rules")
    assert isinstance(rules, list)

    rule_ids = {str(rule.get("id")) for rule in rules if isinstance(rule, dict)}
    assert "ban-ip-solutions-in-ip-engine" in rule_ids
    assert "ban-conjoined-and-tests-in-ip" in rule_ids
    assert "ban-conjoined-and-tests-in-ip-ui" in rule_ids
