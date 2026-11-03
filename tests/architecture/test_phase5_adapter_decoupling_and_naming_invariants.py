"""Phase 5 Architectural Invariant Gate: Zero Adapter-to-Adapter Coupling & Consistent Database Adapter Naming.

Mathematically enforces via AST static analysis across the entire monorepo (ZERO hardcoded file exemptions):
1. Zero `postgres_*.py` filenames and zero `Postgres*` classes anywhere inside `/adapters/`.
2. 100% uniform `SqlAlchemy*` class prefixing for all concrete classes inside `/adapters/outbound/database/` (excluding ORM models, Protocols, TypedDicts, Exceptions, and abstract base classes), and zero `*RepositoryAdapter` suffixes.
3. Zero `*Port` suffixes on concrete non-Protocol classes inside `/adapters/`.
4. All 9 obsolete raw-SQL/duplicate outbox cleanup/repository adapters remain deleted.
5. Zero concrete adapter imports inside any `uow.py`, `tenant_uow_provider.py`, or `uow_factory.py`.
6. Universal Adapter Decoupling across all `/adapters/` modules:
   - Zero cross-package concrete adapter imports (`P.adapters.*` importing `Q.adapters.*` where `Q != P`).
   - Zero cross-direction adapter imports (`inbound` <-> `outbound`, excluding declarative ORM schemas in `database.models`).
   - Zero cross-category outbound adapter imports (`adapters/outbound/<cat_a>` importing `adapters/outbound/<cat_b>`).
   - Zero same-package Composition Root imports (`P.adapters.*` importing `P.bootstrap.*` or `P.container`).
7. Hexagonal Layer Purity across `domain/`, `ports/`, and `application/`:
   - Zero ORM, DB, HTTP, SFTP, Pydantic, FastAPI, cloud SDK, or concrete adapter imports in `domain/`, `ports/`, or `application/`.
   - Strict inward dependency direction (`domain` never imports `ports`/`application`; `ports` never imports `application`).
   - Zero vendor-prefixed classes (`Zitadel*`, `Postgres*`, `SqlAlchemy*`, `Aws*`, etc.) in `domain/`, `ports/`, or `application/`.
8. Centralized Database Engine & Listener Provisioning:
   - Zero imports or calls to `create_async_engine`, `async_sessionmaker`, `get_async_engine`, or `asyncpg.connect` outside `core/platform/packages/database/src/database/` (and Alembic `/migrations/`).
9. `tach.toml` enforces `forbid_circular_dependencies = true`.
10. Zero `# type: ignore`, zero `# ruff: noqa`, and zero `# noqa: C901` complexity suppressions across production `/src/` code.
"""

from __future__ import annotations

import ast
import os
import re
import tomllib
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "__pycache__",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "migrations",
        "bots",
        "grammar",
        "dist",
        ".turbo",
    }
)

_ALLOWED_BASE_OR_HELPER_CLASSES = frozenset(
    {
        "BaseSqlAlchemyRepository",
        "BaseSqlAlchemyUnitOfWork",
        "GlobalSqlAlchemyRepository",
        "TenantSqlAlchemyRepository",
        "DataPlaneStageSqlAlchemyRepository",
    }
)

_NON_CONCRETE_BASE_MARKERS = frozenset(
    {
        "Protocol",
        "ABC",
        "TypedDict",
        "Enum",
        "StrEnum",
        "IntEnum",
        "Exception",
        "RuntimeError",
        "ValueError",
        "DomainError",
    }
)

_DELETED_DUPLICATE_OUTBOX_ADAPTERS: tuple[str, ...] = (
    "core/platform/packages/identity/src/identity/adapters/outbound/database/postgres_identity_outbox_repository.py",
    "core/platform/packages/identity/src/identity/adapters/outbound/database/postgres_identity_outbox_cleanup_repository.py",
    "core/ucp/packages/ucp/src/ucp/adapters/outbound/database/postgres_outbox_repository.py",
    "core/ucp/packages/ucp/src/ucp/adapters/outbound/database/postgres_ucp_outbox_cleanup_repository.py",
    "apps/edi/apps/edi-config-sync-worker/src/config_sync_worker/adapters/outbound/database/postgres_edi_control_plane_outbox_repository.py",
    "apps/edi/apps/edi-cp-jobs-worker/src/edi_cp_jobs_worker/adapters/outbound/database/postgres_edi_control_plane_outbox_cleanup_repository.py",
    "apps/edi/apps/edi-dp-jobs-worker/src/edi_dp_jobs_worker/adapters/outbound/database/sqlalchemy_edi_data_plane_outbox_sweeper_repository.py",
    "apps/edi/apps/edi-dp-jobs-worker/src/edi_dp_jobs_worker/adapters/outbound/database/sqlalchemy_edi_data_plane_outbox_cleanup_repository.py",
    "core/platform/apps/notification-jobs-worker/src/notification_jobs_worker/adapters/outbound/database/postgres_notification_outbox_cleanup_repository.py",
)

_FORBIDDEN_ENGINE_SYMBOLS = frozenset(
    {
        "create_async_engine",
        "async_sessionmaker",
        "get_async_engine",
    }
)


@cache
def _iter_src_python_files() -> tuple[Path, ...]:
    collected: list[Path] = []
    for root in (REPO_ROOT / "core", REPO_ROOT / "apps"):
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    full = Path(dirpath) / fn
                    if "/src/" in full.as_posix():
                        collected.append(full)
    return tuple(collected)


@cache
def _read_and_parse(py_file: Path) -> tuple[str, ast.Module]:
    source = py_file.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(py_file))


def _module_name_for_src_file(py_file: Path) -> str:
    after_src = py_file.relative_to(REPO_ROOT).as_posix().split("/src/", 1)[1]
    mod = after_src[:-3].replace("/", ".")
    if mod.endswith(".__init__"):
        return mod[: -len(".__init__")]
    return mod


def _resolve_import_module(py_file: Path, level: int, module: str | None) -> str:
    if level == 0:
        return module or ""
    self_mod = _module_name_for_src_file(py_file)
    parts = self_mod.split(".")
    base = parts if py_file.name == "__init__.py" else parts[:-1]
    keep = max(0, len(base) - (level - 1))
    prefix = base[:keep]
    if module:
        prefix.append(module)
    return ".".join(prefix)


def _extract_imported_modules(py_file: Path) -> list[tuple[int, str, list[str]]]:
    """Returns `(lineno, resolved_module_path, imported_names)` for all imports in `py_file`."""
    _, tree = _read_and_parse(py_file)
    imports: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name, [alias.name]))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import_module(py_file, node.level, node.module)
            names = [alias.name for alias in node.names]
            imports.append((node.lineno, resolved, names))
    return imports


def _iter_adapter_files() -> list[Path]:
    return [p for p in _iter_src_python_files() if "/adapters/" in p.as_posix()]


def _iter_database_adapter_files() -> list[Path]:
    return [p for p in _iter_src_python_files() if "/adapters/outbound/database/" in p.as_posix()]


def _base_names(cls_node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in cls_node.bases:
        unparsed = ast.unparse(base)
        head = unparsed.split("[", 1)[0].split(".")[-1]
        names.append(head)
    return names


def test_zero_postgres_filenames_and_classes_in_adapters() -> None:
    violations: list[str] = []
    for path in _iter_adapter_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "postgres" in path.name.lower():
            violations.append(f"{rel} uses forbidden `postgres` filename inside `/adapters/`")
        _, tree = _read_and_parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.startswith("Postgres"):
                violations.append(
                    f"{rel}:{node.lineno} class `{node.name}` uses forbidden `Postgres*` prefix inside `/adapters/`"
                )

    assert not violations, (
        "Adapter files and classes must be named by capability or `SqlAlchemy*` ORM convention, never `Postgres*`:\n"
        + "\n".join(violations)
    )


def test_consistent_sqlalchemy_class_prefixes_in_database_adapters() -> None:
    violations: list[str] = []
    for path in _iter_database_adapter_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "/models/" in rel or path.name == "models.py":
            continue
        _, tree = _read_and_parse(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            cls_name = node.name
            if cls_name.startswith("_") or cls_name in _ALLOWED_BASE_OR_HELPER_CLASSES:
                continue
            bases = _base_names(node)
            if any(b in _NON_CONCRETE_BASE_MARKERS or b.endswith("Error") for b in bases):
                continue
            if cls_name.endswith("RepositoryAdapter"):
                violations.append(
                    f"{rel}:{node.lineno} class `{cls_name}` must use `*Repository` (not `*RepositoryAdapter`)"
                )
            elif not cls_name.startswith("SqlAlchemy"):
                violations.append(
                    f"{rel}:{node.lineno} concrete database adapter class `{cls_name}` must use `SqlAlchemy*` prefix"
                )

    assert not violations, "Database adapter class naming drift detected:\n" + "\n".join(violations)


def test_zero_port_suffix_on_concrete_classes_in_adapters() -> None:
    violations: list[str] = []
    for path in _iter_adapter_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        _, tree = _read_and_parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Port"):
                continue
            bases = _base_names(node)
            if "Protocol" in bases:
                continue
            violations.append(
                f"{rel}:{node.lineno} concrete class `{node.name}` in `/adapters/` must not end with `Port`"
            )

    assert not violations, (
        "Concrete classes in `/adapters/` must never masquerade as `*Port` interfaces:\n"
        + "\n".join(violations)
    )


def test_all_nine_obsolete_duplicate_outbox_adapters_remain_deleted() -> None:
    surviving = [rel for rel in _DELETED_DUPLICATE_OUTBOX_ADAPTERS if (REPO_ROOT / rel).exists()]
    assert not surviving, (
        "Obsolete duplicate/raw-SQL outbox adapters must remain deleted:\n" + "\n".join(surviving)
    )


def test_uow_and_uow_provider_files_have_zero_concrete_adapter_imports() -> None:
    target_filenames = {"uow.py", "tenant_uow_provider.py", "uow_factory.py"}
    violations: list[str] = []

    for path in _iter_database_adapter_files():
        if path.name not in target_filenames:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, mod, names in _extract_imported_modules(path):
            if ".adapters." not in mod and not mod.endswith(".adapters"):
                continue
            if ".database.models" in mod or mod.endswith(".models"):
                continue
            violations.append(f"{rel}:{lineno} imports `{names}` from `{mod}`")

    assert not violations, (
        "UoW and UoW provider/factory modules must inject collaborators via Ports from Composition Roots "
        "rather than importing concrete adapters:\n" + "\n".join(violations)
    )


def _parse_adapter_coordinates(mod_path: str) -> tuple[str, str, str] | None:
    """Returns `(package_prefix, direction, category)` for `*.adapters.*` modules."""
    if ".adapters." in mod_path:
        pkg_prefix, _, rest = mod_path.partition(".adapters.")
        parts = rest.split(".")
        if parts[0] in ("inbound", "outbound"):
            category = parts[1] if len(parts) > 1 else ""
            return (pkg_prefix, parts[0], category)
        return (pkg_prefix, "", parts[0])
    if mod_path.endswith(".adapters"):
        return (mod_path[: -len(".adapters")], "", "")
    return None


def test_zero_cross_adapter_or_inverted_bootstrap_couplings_across_monorepo() -> None:
    """Universal monorepo-wide Adapter Decoupling Gate across every file inside `/adapters/`."""
    violations: list[str] = []

    for py_file in _iter_adapter_files():
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        self_mod = _module_name_for_src_file(py_file)
        self_coords = _parse_adapter_coordinates(self_mod)
        if self_coords is None:
            continue
        self_pkg, self_dir, self_cat = self_coords

        for lineno, mod, names in _extract_imported_modules(py_file):
            # 1. Same-package adapter -> bootstrap / container inversion
            if mod in {f"{self_pkg}.container", f"{self_pkg}.bootstrap"} or mod.startswith(
                (f"{self_pkg}.container.", f"{self_pkg}.bootstrap.")
            ):
                violations.append(
                    f"{rel}:{lineno} adapter imports same-package Composition Root `{mod}` ({names})"
                )
                continue

            target_coords = _parse_adapter_coordinates(mod)
            if target_coords is None:
                continue

            # Declarative ORM models inside `...database.models...` are schema declarations
            if ".database.models" in mod or mod.endswith(".database.models"):
                continue

            target_pkg, target_dir, target_cat = target_coords

            # 2. Cross-package concrete adapter coupling
            if target_pkg != self_pkg:
                violations.append(f"{rel}:{lineno} imports cross-package adapter `{mod}` ({names})")
                continue

            # 3. Cross-direction coupling (`inbound` <-> `outbound`)
            if self_dir and target_dir and self_dir != target_dir:
                violations.append(
                    f"{rel}:{lineno} `{self_dir}` adapter imports `{target_dir}` adapter `{mod}` ({names})"
                )
                continue

            # 4. Cross-category outbound adapter coupling (`outbound/<cat_a>` -> `outbound/<cat_b>`)
            if (
                self_dir == "outbound"
                and target_dir == "outbound"
                and self_cat
                and target_cat
                and self_cat != target_cat
            ):
                violations.append(
                    f"{rel}:{lineno} `outbound/{self_cat}` adapter imports sibling `outbound/{target_cat}` adapter `{mod}` ({names})"
                )

    assert not violations, "Universal Adapter Decoupling violation detected:\n" + "\n".join(
        violations
    )


def _resolve_core_layer(after_src: str) -> str | None:
    """Returns 'domain', 'ports', or 'application' if `after_src` belongs to a core layer."""
    for layer in ("domain", "ports", "application"):
        token = f"/{layer}/"
        if token in after_src:
            if "/adapters/" in after_src and after_src.index("/adapters/") < after_src.index(token):
                return None
            return layer
    return None


def test_zero_infrastructure_or_vendor_leaks_in_domain_ports_and_application_layers() -> None:
    """Monorepo-wide Hexagonal Purity Gate across `domain/`, `ports/`, and `application/`."""
    forbidden_infra_packages = frozenset(
        {
            "sqlalchemy",
            "httpx",
            "boto3",
            "botocore",
            "asyncpg",
            "fastapi",
            "pydantic",
            "shttp",
            "sftp",
            "database",
            "ucp_models",
            "aioboto3",
            "paramiko",
            "jinja2",
        }
    )
    forbidden_vendor_class_prefixes = (
        "Zitadel",
        "Postgres",
        "SqlAlchemy",
        "Aws",
        "Sqs",
        "Sns",
        "SendGrid",
        "Bots",
        "Jinja",
    )

    violations: list[str] = []
    for path in _iter_src_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        after_src = rel.split("/src/", 1)[1]
        layer = _resolve_core_layer(after_src)
        if layer is None:
            continue

        _, tree = _read_and_parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.startswith(
                forbidden_vendor_class_prefixes
            ):
                violations.append(
                    f"{rel}:{node.lineno} defines vendor/infra-named class `{node.name}` inside `{layer}/`"
                )

        for lineno, mod, names in _extract_imported_modules(path):
            top = mod.lstrip(".").split(".")[0]
            if (
                top in forbidden_infra_packages
                or ".adapters." in mod
                or ".bootstrap." in mod
                or mod.endswith((".adapters", ".bootstrap", ".container"))
            ):
                violations.append(f"{rel}:{lineno} (`{layer}`) imports `{names}` from `{mod}`")
                continue

            if layer == "domain" and (
                ".ports." in mod
                or ".application." in mod
                or mod.endswith((".ports", ".application"))
            ):
                violations.append(
                    f"{rel}:{lineno} (`domain`) imports outer layer `{mod}` ({names})"
                )
            elif layer == "ports" and (".application." in mod or mod.endswith(".application")):
                violations.append(
                    f"{rel}:{lineno} (`ports`) imports outer `application` layer `{mod}` ({names})"
                )

    assert not violations, (
        "Hexagonal layer purity violation detected in `domain/`, `ports/`, or `application/`:\n"
        + "\n".join(violations)
    )


def test_centralized_database_provider_no_raw_engine_or_asyncpg_outside_database_pkg() -> None:
    """Enforces centralized `DatabaseProvider` usage across all non-migration `/src/` code."""
    violations: list[str] = []
    allowed_prefix = "core/platform/packages/database/src/database/"

    for path in _iter_src_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(allowed_prefix):
            continue

        for lineno, mod, names in _extract_imported_modules(path):
            if mod == "asyncpg" or mod.startswith("asyncpg."):
                violations.append(f"{rel}:{lineno} imports `asyncpg` outside `database` package")
            overlap = _FORBIDDEN_ENGINE_SYMBOLS.intersection(names)
            if overlap:
                violations.append(
                    f"{rel}:{lineno} imports `{sorted(overlap)}` from `{mod}` instead of using `DatabaseProvider`"
                )

    assert not violations, (
        "Direct engine/sessionmaker/asyncpg provisioning detected outside `core/platform/packages/database/`:\n"
        + "\n".join(violations)
    )


def test_tach_forbids_circular_dependencies() -> None:
    tach_path = REPO_ROOT / "tach.toml"
    config = tomllib.loads(tach_path.read_text(encoding="utf-8"))
    assert config.get("forbid_circular_dependencies") is True, (
        "`tach.toml` must enforce `forbid_circular_dependencies = true`."
    )


def test_zero_type_ignore_global_noqa_or_c901_suppressions() -> None:
    violations: list[str] = []
    type_ignore_re = re.compile(r"#\s*type:\s*ignore\b")
    global_ruff_noqa_re = re.compile(r"^\s*#\s*ruff:\s*noqa\b")
    c901_noqa_re = re.compile(r"#\s*noqa\b[^\n]*\bC901\b")

    for path in _iter_src_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        source, _ = _read_and_parse(path)
        for lineno, line in enumerate(source.splitlines(), start=1):
            if type_ignore_re.search(line):
                violations.append(f"{rel}:{lineno} uses forbidden `# type: ignore`")
            if global_ruff_noqa_re.search(line):
                violations.append(f"{rel}:{lineno} uses forbidden file-level `# ruff: noqa`")
            if c901_noqa_re.search(line):
                violations.append(f"{rel}:{lineno} suppresses complexity with `# noqa: C901`")

    assert not violations, (
        "Forbidden static analysis or complexity suppression detected:\n" + "\n".join(violations)
    )
