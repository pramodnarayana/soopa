"""AST-based Architectural Invariant Gate for Phase 4 (Reflection-Free Data Mappers & Zero getattr Masking)."""

from __future__ import annotations

import ast
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_BANNED_DIRECT_CALLS = frozenset({"getattr", "hasattr", "fields", "asdict"})
_BANNED_ATTR_CALLS = frozenset({"fields", "asdict"})
_BANNED_ATTRIBUTES = frozenset({"__dict__", "_mapping", "_state"})
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
        "tests",
    }
)


def _iter_src_py_files() -> list[Path]:
    files: list[Path] = []
    for root_name in ("core", "apps"):
        root = _REPO_ROOT / root_name
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    files.append(Path(dirpath) / fn)
    return files


def _collect_database_adapter_files() -> list[Path]:
    return [p for p in _iter_src_py_files() if "adapters" in p.parts and "database" in p.parts]


def _collect_phase4_runtime_boundary_files() -> list[Path]:
    explicit_paths = (
        "apps/edi/packages/edi/src/edi/domain/replication/graph.py",
        "apps/edi/packages/edi/src/edi/adapters/outbound/database/replication_registry.py",
        "apps/edi/packages/edi/src/edi/adapters/outbound/database/replication_adapter.py",
        "apps/edi/packages/edi/src/edi/bootstrap/lifespan.py",
        "apps/edi/packages/edi/src/edi/module.py",
        "apps/edi/apps/edi-as2-server/src/as2_server/main.py",
        "apps/edi/apps/edi-as2-server/src/as2_server/dependencies.py",
        "apps/edi/apps/edi-as2-server/src/as2_server/adapters/inbound/http/routers/ops.py",
        "core/platform/apps/unified-api/src/unified_api/main.py",
        "core/platform/apps/unified-api/src/unified_api/bootstrap/lifespan.py",
        "core/platform/apps/unified-api/src/unified_api/adapters/inbound/http/middleware/authentication.py",
        "core/platform/apps/unified-api/src/unified_api/adapters/inbound/http/middleware/tenant_context.py",
        "core/platform/packages/database/src/database/interceptors.py",
    )
    return [_REPO_ROOT / rel for rel in explicit_paths]


def _inspect_node_violation(rel: Path, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _BANNED_DIRECT_CALLS:
            return [f"{rel}:{node.lineno}: forbidden reflection call '{node.func.id}(...)'"]
        if isinstance(node.func, ast.Attribute) and node.func.attr in _BANNED_ATTR_CALLS:
            return [f"{rel}:{node.lineno}: forbidden reflection call '.{node.func.attr}(...)'"]
        return []
    if isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRIBUTES:
        return [f"{rel}:{node.lineno}: forbidden private/reflection attribute '.{node.attr}'"]
    if isinstance(node, ast.Import):
        return [
            f"{rel}:{node.lineno}: forbidden 'import logging'"
            for alias in node.names
            if alias.name == "logging"
        ]
    return []


def _audit_ast_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        rel = path.relative_to(_REPO_ROOT)
        source = path.read_text(encoding="utf-8")
        if "# type: ignore" in source:
            violations.append(f"{rel}: contains forbidden '# type: ignore'")

        tree = ast.parse(source, filename=str(rel))
        for node in ast.walk(tree):
            violations.extend(_inspect_node_violation(rel, node))
    return violations


def _collect_domain_and_ports_files() -> list[Path]:
    files: list[Path] = []
    for path in _iter_src_py_files():
        posix = path.as_posix()
        if "/src/" not in posix:
            continue
        after_src = posix.split("/src/", 1)[1]
        # Internal third-party/parser subpackages (bots / transformer adapter internals)
        if "edi/core/bots/" in after_src:
            continue
        if "/adapters/" in after_src and (
            (
                "/domain/" in after_src
                and after_src.index("/adapters/") < after_src.index("/domain/")
            )
            or (
                "/ports/" in after_src
                and after_src.index("/adapters/") < after_src.index("/ports/")
            )
        ):
            continue
        if "/domain/" in after_src or "/ports/" in after_src:
            files.append(path)
    return files


def test_all_database_adapters_and_phase4_boundaries_are_reflection_free() -> None:
    db_files = _collect_database_adapter_files()
    domain_and_ports_files = _collect_domain_and_ports_files()
    boundary_files = _collect_phase4_runtime_boundary_files()
    assert len(db_files) >= 50, "Expected to discover monorepo database adapter files"
    assert len(domain_and_ports_files) >= 100, "Expected to discover monorepo domain & ports files"

    all_targets = sorted(set(db_files) | set(domain_and_ports_files) | set(boundary_files))
    violations = _audit_ast_violations(all_targets)
    assert violations == [], "Phase 4 AST architectural violations detected:\n" + "\n".join(
        violations
    )


def test_obsolete_duplicate_raw_sql_outbox_adapters_remain_deleted() -> None:
    deleted_paths = (
        "core/platform/packages/identity/src/identity/adapters/outbound/database/postgres_identity_outbox_repository.py",
        "core/platform/packages/identity/src/identity/adapters/outbound/database/postgres_identity_outbox_cleanup_repository.py",
        "core/ucp/packages/ucp/src/ucp/adapters/outbound/database/postgres_outbox_repository.py",
        "core/ucp/packages/ucp/src/ucp/adapters/outbound/database/postgres_ucp_outbox_cleanup_repository.py",
        "apps/edi/apps/edi-config-sync-worker/src/config_sync_worker/adapters/outbound/database/postgres_edi_control_plane_outbox_repository.py",
        "apps/edi/apps/edi-cp-jobs-worker/src/edi_cp_jobs_worker/adapters/outbound/database/postgres_edi_control_plane_outbox_cleanup_repository.py",
        "apps/edi/apps/edi-dp-jobs-worker/src/edi_dp_jobs_worker/adapters/outbound/database/sqlalchemy_edi_data_plane_outbox_sweeper_repository.py",
        "apps/edi/apps/edi-dp-jobs-worker/src/edi_dp_jobs_worker/adapters/outbound/database/sqlalchemy_edi_data_plane_outbox_cleanup_repository.py",
    )
    still_present = [rel for rel in deleted_paths if (_REPO_ROOT / rel).exists()]
    assert still_present == [], f"Duplicate outbox adapters must remain deleted: {still_present}"
