import ast
from pathlib import Path


def get_use_case_files() -> list[Path]:
    """Finds all Python files inside 'use_cases' directories across the monorepo."""
    root_dir = Path(__file__).parent.parent.parent
    use_case_files = []

    for path in root_dir.rglob("use_cases/**/*.py"):
        # Exclude venv, node_modules, tests directories, test files, and __init__.py
        if (
            ".venv" in path.parts
            or "node_modules" in path.parts
            or "tests" in path.parts
            or path.name.startswith("test_")
            or path.name == "__init__.py"
        ):
            continue
        use_case_files.append(path)

    return use_case_files


def test_use_case_file_naming():
    """All files in use_cases directories must end with _use_case.py"""
    use_case_files = get_use_case_files()
    assert len(use_case_files) > 0, "No use case files found, check search path."

    violations = []
    for filepath in use_case_files:
        if not filepath.name.endswith("_use_case.py"):
            violations.append(str(filepath))

    assert not violations, (
        f"The following files violate the naming convention (must end in _use_case.py): {violations}"
    )


def test_use_case_class_structure():
    """
    Every file ending with _use_case.py must:
    1. Define exactly one class ending with 'UseCase'.
    2. That class must have exactly ONE public method (typically 'execute').
    """
    use_case_files = get_use_case_files()
    class_name_violations = []
    public_method_violations = []
    syntax_errors = []

    for filepath in use_case_files:
        if not filepath.name.endswith("_use_case.py"):
            continue

        with open(filepath) as f:
            source = f.read()

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            syntax_errors.append(f"{filepath.name}: SyntaxError at line {e.lineno}: {e.msg}")
            continue

        use_case_classes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("UseCase")
        ]

        if len(use_case_classes) != 1:
            class_name_violations.append(
                f"{filepath.name}: expected exactly 1 class ending with 'UseCase', found {len(use_case_classes)}"
            )
            continue

        use_case_class = use_case_classes[0]
        public_methods = [
            node.name
            for node in use_case_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        ]

        if len(public_methods) != 1:
            public_method_violations.append(
                f"{filepath.name} ({use_case_class.name}): expected exactly 1 public method, found {len(public_methods)} -> {public_methods}"
            )

    assert not syntax_errors, "Use Case Syntax Errors:\n" + "\n".join(syntax_errors)
    assert not class_name_violations, "Use Case Class Naming Violations:\n" + "\n".join(
        class_name_violations
    )
    assert not public_method_violations, (
        "Use Case Public Method Violations (God Service Anti-Pattern):\n"
        + "\n".join(public_method_violations)
    )
