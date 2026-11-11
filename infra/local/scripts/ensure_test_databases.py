"""Idempotently provisions, initializes, migrates, and seeds isolated *_test PostgreSQL databases."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import structlog
from database.utils import (
    build_maintenance_dsn,
    extract_database_name,
    is_postgres_dsn,
    normalize_to_standard_postgres,
    rewrite_dsn_to_test_db,
)
from drop_schemas import DOMAIN_SHARD_ENV_VARS
from seedwork.infra.config import load_repo_env

logger = structlog.get_logger(__name__)

GLOBAL_DB_ENV_KEYS: frozenset[str] = frozenset({"DATABASE_URL", "GLOBAL_DATABASE_URL"})
EXPLICIT_SHARD_DB_ENV_KEYS: frozenset[str] = frozenset(
    {"TEST_SHARD_DB_URL", "SHARD_1_URL", "DB_SHARD_1_URL"}
)
VALID_DB_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SYNC_STATE_ROW_ID = "v1"


@dataclass(frozen=True)
class TestDatabaseTarget:
    """Resolved PostgreSQL test database target on an existing running container."""

    db_name: str
    dsn: str
    maintenance_dsn: str
    is_global: bool


def is_database_url_env_key(key: str) -> bool:
    """Return True when an environment variable key holds an application/shard DB DSN."""
    if key in GLOBAL_DB_ENV_KEYS or key in EXPLICIT_SHARD_DB_ENV_KEYS:
        return True
    if key.endswith("_DATABASE_URL"):
        return True
    return key.startswith(("SHARD_OVERRIDES__", "DATABASE__SHARD_OVERRIDES__"))


def rewrite_database_env_vars(env: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` with all PostgreSQL DSN variables rewritten to ``*_test``."""
    rewritten = dict(env)
    for key, val in env.items():
        if not is_database_url_env_key(key):
            continue
        stripped = val.strip()
        if not stripped:
            continue
        if is_postgres_dsn(stripped):
            rewritten[key] = rewrite_dsn_to_test_db(stripped)
    return rewritten


def discover_test_database_targets(env: Mapping[str, str]) -> list[TestDatabaseTarget]:
    """Discover deduplicated global and shard ``*_test`` database targets from ``env``."""
    rewritten = rewrite_database_env_vars(env)
    ordered_keys: list[str] = [k for k in ("DATABASE_URL", "GLOBAL_DATABASE_URL") if k in rewritten]
    ordered_keys.extend(
        sorted(k for k in rewritten if is_database_url_env_key(k) and k not in GLOBAL_DB_ENV_KEYS)
    )

    targets: list[TestDatabaseTarget] = []
    seen: set[tuple[str, str]] = set()

    for key in ordered_keys:
        raw_url = rewritten.get(key, "").strip()
        if not is_postgres_dsn(raw_url):
            continue
        db_name = extract_database_name(raw_url)
        if not db_name:
            continue
        std_dsn = normalize_to_standard_postgres(raw_url)
        maint_dsn = build_maintenance_dsn(std_dsn)
        dedup_key = (maint_dsn, db_name)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        targets.append(
            TestDatabaseTarget(
                db_name=db_name,
                dsn=std_dsn,
                maintenance_dsn=maint_dsn,
                is_global=(key in GLOBAL_DB_ENV_KEYS),
            )
        )

    return targets


def _target_identity_from_dsn(raw_url: str) -> tuple[str, str] | None:
    stripped = raw_url.strip()
    if not is_postgres_dsn(stripped):
        return None
    db_name = extract_database_name(stripped)
    if not db_name:
        return None
    std_dsn = normalize_to_standard_postgres(stripped)
    return (build_maintenance_dsn(std_dsn), db_name)


def _collect_domain_target_identities(
    rewritten_env: Mapping[str, str],
    domains: Sequence[str],
) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    for domain in domains:
        mapped_keys = set(DOMAIN_SHARD_ENV_VARS.get(domain, ()))
        upper_domain = domain.upper()
        for env_key in rewritten_env:
            if env_key == f"{upper_domain}_DATABASE_URL" or env_key.startswith(
                (
                    f"SHARD_OVERRIDES__{upper_domain}_",
                    f"DATABASE__SHARD_OVERRIDES__{upper_domain}_",
                )
            ):
                mapped_keys.add(env_key)
        for key in mapped_keys:
            ident = _target_identity_from_dsn(rewritten_env.get(key, ""))
            if ident is not None:
                identities.add(ident)
    return identities


def filter_targets_for_active_domains(
    targets: Sequence[TestDatabaseTarget],
    rewritten_env: Mapping[str, str],
    active_domains: Sequence[str],
    *,
    domains_arg: str = "all",
) -> list[TestDatabaseTarget]:
    """Retain global and active-domain shard targets while excluding inactive domain shards."""
    active_set = set(active_domains)
    inactive_domains = [d for d in DOMAIN_SHARD_ENV_VARS if d not in active_set]
    active_identities = _collect_domain_target_identities(rewritten_env, active_domains)
    inactive_identities = _collect_domain_target_identities(rewritten_env, inactive_domains)
    unscoped = domains_arg.strip().lower() in ("", "all")

    filtered: list[TestDatabaseTarget] = []
    for target in targets:
        ident = (target.maintenance_dsn, target.db_name)
        if target.is_global or ident in active_identities:
            filtered.append(target)
        elif ident in inactive_identities:
            continue
        elif unscoped:
            filtered.append(target)
    return filtered


def resolve_active_app_domains(root_dir: Path, domains_arg: str) -> list[str]:
    """Resolve active bounded-context app directory names under ``apps/``."""
    apps_dir = root_dir / "apps"
    if not apps_dir.is_dir():
        return []

    available = sorted(
        child.name
        for child in apps_dir.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and (
            (child / "scripts" / "seed_jobs.py").is_file()
            or any(child.glob("**/run_migrations.py"))
        )
    )
    normalized = domains_arg.strip().lower()
    if normalized in ("", "all"):
        return available

    requested = [
        token.strip().lower()
        for token in normalized.split(",")
        if token.strip() and token.strip().lower() != "platform"
    ]
    return [name for name in requested if name in available]


def discover_app_migration_modules(root_dir: Path, app_domains: Sequence[str]) -> list[str]:
    """Discover ``<pkg>.**.run_migrations`` module paths dynamically for active apps."""
    modules: list[str] = []
    apps_dir = root_dir / "apps"
    for app_name in app_domains:
        app_root = apps_dir / app_name
        for script_path in sorted(app_root.glob("packages/*/src/**/run_migrations.py")):
            parts = script_path.parts
            if "src" not in parts:
                continue
            src_index = parts.index("src")
            rel_parts = parts[src_index + 1 :]
            if not rel_parts:
                continue
            module_parts = [*rel_parts[:-1], Path(rel_parts[-1]).stem]
            modules.append(".".join(module_parts))
    return modules


_IGNORED_WALK_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".venv", "__pycache__", "dist", "build", ".turbo", ".git"}
)


def _discover_seed_scripts(base_dir: Path) -> list[Path]:
    """Find ``scripts/seed*.py`` under ``base_dir`` without traversing ``node_modules`` or ``.venv``."""
    if not base_dir.is_dir():
        return []
    found: list[Path] = []
    for root, dirs, files in os.walk(base_dir, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _IGNORED_WALK_DIRS]
        if os.path.basename(root) != "scripts":
            continue
        for filename in files:
            if filename.startswith("seed") and filename.endswith(".py"):
                found.append(Path(root) / filename)
    return sorted(found)


def compute_schema_and_seed_fingerprint(
    root_dir: Path,
    env: Mapping[str, str],
    app_domains: Sequence[str],
) -> str:
    """Compute a fast SHA-256 digest over migration files, seed scripts, and seeded env vars."""
    hasher = hashlib.sha256()

    tracked_files: list[Path] = []
    init_sql = root_dir / "infra" / "local" / "init.sql"
    if init_sql.is_file():
        tracked_files.append(init_sql)

    reconcile_script = root_dir / "infra" / "local" / "scripts" / "reconcile_schema_drift.py"
    if reconcile_script.is_file():
        tracked_files.append(reconcile_script)

    migrations_dir = root_dir / "core" / "platform" / "packages" / "database" / "migrations"
    if migrations_dir.is_dir():
        tracked_files.extend(
            sorted(p for p in migrations_dir.rglob("*.py") if "node_modules" not in p.parts)
        )
    tracked_files.extend(_discover_seed_scripts(root_dir / "core"))

    for app_name in app_domains:
        app_root = root_dir / "apps" / app_name
        if app_root.is_dir():
            tracked_files.extend(
                sorted(
                    p
                    for p in app_root.glob("packages/*/src/**/migrations/**/*.py")
                    if "node_modules" not in p.parts
                )
            )
            tracked_files.extend(_discover_seed_scripts(app_root))

    for file_path in tracked_files:
        if file_path.is_file():
            rel = str(file_path.relative_to(root_dir))
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(file_path.read_bytes())
            hasher.update(b"\0")

    seed_sensitive_keys = sorted(
        k
        for k in env
        if is_database_url_env_key(k)
        or k
        in {
            "IDENTITY_PLATFORM_ORG_ID",
            "IDENTITY_PLATFORM_ADMIN_ID",
            "IDENTITY_EDI_PROJECT_ID",
            "IDENTITY_UCP_PROJECT_ID",
        }
    )
    for key in seed_sensitive_keys:
        hasher.update(f"{key}={env.get(key, '')}\n".encode())

    hasher.update(f"domains={','.join(app_domains)}\n".encode())
    return hasher.hexdigest()


async def _ensure_single_database_exists(target: TestDatabaseTarget) -> bool:
    """Create ``target.db_name`` if missing; return True when newly created."""
    if not VALID_DB_IDENTIFIER_RE.match(target.db_name):
        raise ValueError(f"Unsafe PostgreSQL database identifier: {target.db_name!r}")

    conn = await asyncpg.connect(target.maintenance_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            target.db_name,
        )
        if exists:
            return False
        await conn.execute(f'CREATE DATABASE "{target.db_name}"')
        logger.info("test_database_created", db_name=target.db_name)
        return True
    finally:
        await conn.close()


async def _apply_global_init_sql(global_target: TestDatabaseTarget, init_sql_path: Path) -> None:
    """Ensure ``platform.current_tenant_id()`` and ``platform.bypass_rls()`` exist."""
    if not init_sql_path.is_file():
        return
    sql_text = init_sql_path.read_text(encoding="utf-8")
    conn = await asyncpg.connect(global_target.dsn)
    try:
        await conn.execute(sql_text)
    finally:
        await conn.close()


async def _is_sync_state_current(
    targets: Sequence[TestDatabaseTarget],
    expected_fingerprint: str,
) -> bool:
    """Return True if global_db_test holds the current fingerprint and all shards are migrated."""
    global_targets = [t for t in targets if t.is_global]
    if not global_targets:
        return False

    global_conn = await asyncpg.connect(global_targets[0].dsn)
    try:
        table_exists = await global_conn.fetchval(
            "SELECT to_regclass('platform._test_db_sync_state')"
        )
        if table_exists is None:
            return False
        stored_fp = await global_conn.fetchval(
            "SELECT fingerprint FROM platform._test_db_sync_state WHERE id = $1",
            SYNC_STATE_ROW_ID,
        )
        if stored_fp != expected_fingerprint:
            return False
    finally:
        await global_conn.close()

    for shard_target in (t for t in targets if not t.is_global):
        shard_conn = await asyncpg.connect(shard_target.dsn)
        try:
            has_alembic = await shard_conn.fetchval("SELECT to_regclass('public.alembic_version')")
            if has_alembic is None:
                return False
        finally:
            await shard_conn.close()

    return True


async def _record_sync_fingerprint(
    global_target: TestDatabaseTarget,
    fingerprint: str,
) -> None:
    conn = await asyncpg.connect(global_target.dsn)
    try:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS platform")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform._test_db_sync_state (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO platform._test_db_sync_state (id, fingerprint, synced_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (id) DO UPDATE
            SET fingerprint = EXCLUDED.fingerprint,
                synced_at = NOW()
            """,
            SYNC_STATE_ROW_ID,
            fingerprint,
        )
    finally:
        await conn.close()


def _run_python_module(
    module_name: str,
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    cmd = [sys.executable, "-m", module_name, *args]
    subprocess.run(cmd, cwd=cwd, env=dict(env), check=True)  # noqa: S603 - Trusted internal Python module execution via sys.executable


def _run_python_script(
    script_path: Path,
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    cmd = [sys.executable, str(script_path), *args]
    subprocess.run(cmd, cwd=cwd, env=dict(env), check=True)  # noqa: S603 - Trusted internal repo script execution via sys.executable


async def ensure_test_databases_ready(
    *,
    root_dir: Path,
    env: Mapping[str, str],
    domains: str = "all",
    force_sync: bool = False,
) -> dict[str, str]:
    """Ensure all ``*_test`` databases exist, have RLS functions, and match current migrations/seeds."""
    test_env = rewrite_database_env_vars(env)
    active_apps = resolve_active_app_domains(root_dir, domains)
    targets = filter_targets_for_active_domains(
        discover_test_database_targets(test_env),
        test_env,
        active_apps,
        domains_arg=domains,
    )
    if not targets:
        raise RuntimeError("No PostgreSQL DSN variables found to provision test databases.")

    newly_created = False
    for target in targets:
        created = await _ensure_single_database_exists(target)
        newly_created = newly_created or created

    global_targets = [t for t in targets if t.is_global]
    if global_targets:
        await _apply_global_init_sql(global_targets[0], root_dir / "infra" / "local" / "init.sql")

    fingerprint = compute_schema_and_seed_fingerprint(root_dir, test_env, active_apps)
    if not force_sync and not newly_created and await _is_sync_state_current(targets, fingerprint):
        logger.info(
            "test_databases_already_up_to_date",
            databases=[t.db_name for t in targets],
        )
        return test_env

    logger.info(
        "test_databases_synchronizing",
        databases=[t.db_name for t in targets],
        active_apps=active_apps,
    )
    _run_python_module(
        "platform_migrator",
        ["migrate", "--domain", "platform"],
        cwd=root_dir,
        env=test_env,
    )
    _run_python_script(
        root_dir / "infra" / "local" / "scripts" / "reconcile_schema_drift.py",
        ["--domain", "platform"],
        cwd=root_dir,
        env=test_env,
    )

    _run_python_module(
        "platform_migrator",
        ["seed", "--domain", "platform"],
        cwd=root_dir,
        env=test_env,
    )
    for app_domain in active_apps:
        _run_python_module(
            "platform_migrator",
            ["seed", "--domain", app_domain],
            cwd=root_dir,
            env=test_env,
        )

    for migration_module in discover_app_migration_modules(root_dir, active_apps):
        _run_python_module(migration_module, [], cwd=root_dir, env=test_env)

    for app_domain in active_apps:
        _run_python_script(
            root_dir / "infra" / "local" / "scripts" / "reconcile_schema_drift.py",
            ["--domain", app_domain],
            cwd=root_dir,
            env=test_env,
        )

    if global_targets:
        await _record_sync_fingerprint(global_targets[0], fingerprint)

    logger.info(
        "test_databases_ready",
        databases=[t.db_name for t in targets],
    )
    return test_env


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision, migrate, and seed isolated *_test PostgreSQL databases."
    )
    parser.add_argument(
        "--domains",
        type=str,
        default=os.environ.get("ENABLED_APPS", "all"),
        help="Comma-separated domains to seed/migrate (default: all)",
    )
    parser.add_argument(
        "--force-sync",
        action="store_true",
        help="Force running Alembic migrations and seed scripts even when fingerprint matches",
    )
    parsed = parser.parse_args(argv)

    root_dir = Path(__file__).resolve().parents[3]
    load_repo_env(repo_root=root_dir, override=False)
    try:
        asyncio.run(
            ensure_test_databases_ready(
                root_dir=root_dir,
                env=os.environ,
                domains=parsed.domains,
                force_sync=parsed.force_sync,
            )
        )
        return 0
    except Exception as exc:
        logger.exception("ensure_test_databases_failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
