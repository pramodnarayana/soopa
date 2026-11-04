"""Executes commands inside an isolated *_test database and optional hermetic env-file sandbox."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import structlog
from dotenv import dotenv_values
from ensure_test_databases import ensure_test_databases_ready, rewrite_database_env_vars
from seedwork.infra.config import ENV_FILE_SELECTOR_VAR
from sync_topology import compose_topology_env_mappings

logger = structlog.get_logger(__name__)

PASSTHROUGH_SYSTEM_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "VIRTUAL_ENV",
        "UV_CACHE_DIR",
        "UV_PYTHON",
        "PNPM_HOME",
        "NVM_DIR",
        "NODE_OPTIONS",
        "COREPACK_ENABLE_STRICT",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "SSH_AUTH_SOCK",
        "SYSTEMROOT",
        "CI",
        "COVERAGE_FILE",
        "TURBO_CONCURRENCY",
        "TURBO_TOKEN",
        "TURBO_TEAM",
        "TURBO_REMOTE_ONLY",
        "FORCE_COLOR",
        "NO_COLOR",
        "PYTHONPATH",
        "PYTEST_PLUGINS",
        "ENABLED_APPS",
    }
)

ROOT_ESCALATION_FILENAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "turbo.json",
        ".env.example",
        "semgrep-architecture.yml",
        ".semgrep/enterprise-rules.yml",
        "infra/local/init.sql",
        "scripts/verify_ci.sh",
        "scripts/aggregate_coverage.py",
    }
)


def should_escalate_to_full_verification(changed_files: Sequence[str]) -> bool:
    """Return True if any changed path modifies root configuration requiring full-repo checks."""
    for raw_path in changed_files:
        normalized = raw_path.strip().removeprefix("./")
        if not normalized:
            continue
        if normalized in ROOT_ESCALATION_FILENAMES:
            return True
        if normalized.startswith((".github/actions/", "infra/local/scripts/")):
            return True
    return False


def build_hermetic_test_environment(
    *,
    root_dir: Path,
    env_file: Path,
    base_environ: Mapping[str, str],
    domains: str = "all",
) -> dict[str, str]:
    """Construct a clean-room child environment from ``env_file`` without touching ``.env``.

    Strips ambient developer secrets and ``.env`` variables so missing entries in
    ``.env.example`` fail deterministically, injects dynamic LocalStack topology
    URLs in memory, blocks ambient AWS credentials, and rewrites all PostgreSQL
    DSNs to isolated ``*_test`` databases.
    """
    resolved_env_file = env_file if env_file.is_absolute() else (root_dir / env_file)
    if not resolved_env_file.is_file():
        raise FileNotFoundError(f"Environment file not found: {resolved_env_file}")

    clean_env: dict[str, str] = {}
    for key in PASSTHROUGH_SYSTEM_ENV_KEYS:
        if key in base_environ:
            clean_env[key] = base_environ[key]

    parsed_file_values = dotenv_values(resolved_env_file)
    for key, val in parsed_file_values.items():
        if val is not None:
            clean_env[key] = val

    topology_mappings = compose_topology_env_mappings(root_dir, domains=domains)
    clean_env.update(topology_mappings)

    clean_env[ENV_FILE_SELECTOR_VAR] = str(resolved_env_file)
    clean_env["AWS_SHARED_CREDENTIALS_FILE"] = "/dev/null"
    clean_env["AWS_CONFIG_FILE"] = "/dev/null"

    return rewrite_database_env_vars(clean_env)


def build_interactive_test_environment(
    *,
    root_dir: Path,
    env_file: Path,
    base_environ: Mapping[str, str],
    domains: str = "all",
) -> dict[str, str]:
    """Construct a test environment preserving caller env vars while isolating DBs to ``*_test``."""
    resolved_env_file = env_file if env_file.is_absolute() else (root_dir / env_file)
    merged: dict[str, str] = dict(base_environ)

    if resolved_env_file.is_file():
        for key, val in dotenv_values(resolved_env_file).items():
            if val is not None and key not in merged:
                merged[key] = val
        merged.setdefault(ENV_FILE_SELECTOR_VAR, str(resolved_env_file))

    for key, val in compose_topology_env_mappings(root_dir, domains=domains).items():
        merged.setdefault(key, val)

    merged.setdefault("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    merged.setdefault("AWS_CONFIG_FILE", "/dev/null")

    return rewrite_database_env_vars(merged)


def resolve_verification_scope(
    *,
    root_dir: Path,
    base_ref: str | None,
) -> tuple[str, str]:
    """Determine ``("full", "")`` or ``("affected", "--filter=...[<base>]")`` for pre-push."""
    git_bin = shutil.which("git")
    if not git_bin:
        return ("full", "")

    candidate_refs: list[str] = []
    if base_ref:
        candidate_refs.append(base_ref)
    else:
        upstream_proc = subprocess.run(  # noqa: S603 - Safe git executable resolved via shutil.which
            [git_bin, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=root_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if upstream_proc.returncode == 0 and upstream_proc.stdout.strip():
            candidate_refs.append(upstream_proc.stdout.strip())
        candidate_refs.extend(["origin/development", "origin/main"])

    resolved_base: str | None = None
    for ref in candidate_refs:
        verify_proc = subprocess.run(  # noqa: S603 - Safe git executable resolved via shutil.which
            [git_bin, "merge-base", ref, "HEAD"],
            cwd=root_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if verify_proc.returncode == 0 and verify_proc.stdout.strip():
            resolved_base = verify_proc.stdout.strip()
            break

    if not resolved_base:
        return ("full", "")

    diff_proc = subprocess.run(  # noqa: S603 - Safe git executable resolved via shutil.which
        [git_bin, "diff", "--name-only", f"{resolved_base}..HEAD"],
        cwd=root_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_proc.returncode != 0:
        return ("full", "")

    changed_files = [line.strip() for line in diff_proc.stdout.splitlines() if line.strip()]
    if not changed_files:
        return ("affected_empty", resolved_base)

    if should_escalate_to_full_verification(changed_files):
        return ("full", resolved_base)

    return ("affected", resolved_base)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a command against isolated *_test databases without mutating .env."
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=os.environ.get(ENV_FILE_SELECTOR_VAR, ".env"),
        help="Environment file to load in memory (e.g. .env.example or .env)",
    )
    parser.add_argument(
        "--hermetic",
        action="store_true",
        help="Strip ambient developer environment variables for strict CI parity",
    )
    parser.add_argument(
        "--domains",
        type=str,
        default=os.environ.get("ENABLED_APPS", "all"),
        help="Active bounded-context domains (default: all)",
    )
    parser.add_argument(
        "--skip-db-ensure",
        action="store_true",
        help="Skip PostgreSQL *_test database provisioning/migration check",
    )
    parser.add_argument(
        "--force-db-sync",
        action="store_true",
        help="Force running migrations and seeds on *_test databases",
    )
    parser.add_argument(
        "--print-scope",
        action="store_true",
        help="Print verification scope ('full <base>' or 'affected <base>') and exit",
    )
    parser.add_argument(
        "--base-ref",
        type=str,
        default=None,
        help="Optional git base ref for --print-scope",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command and arguments to execute (after '--')",
    )

    parsed = parser.parse_args(argv)
    root_dir = Path(__file__).resolve().parents[3]

    if parsed.print_scope:
        mode, resolved_base = resolve_verification_scope(
            root_dir=root_dir,
            base_ref=parsed.base_ref,
        )
        sys.stdout.write(f"{mode} {resolved_base}\n")
        return 0

    cmd = list(parsed.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("No command specified after '--'")

    env_file_path = Path(parsed.env_file)
    if parsed.hermetic:
        child_env = build_hermetic_test_environment(
            root_dir=root_dir,
            env_file=env_file_path,
            base_environ=os.environ,
            domains=parsed.domains,
        )
    else:
        child_env = build_interactive_test_environment(
            root_dir=root_dir,
            env_file=env_file_path,
            base_environ=os.environ,
            domains=parsed.domains,
        )

    if not parsed.skip_db_ensure:
        child_env = asyncio.run(
            ensure_test_databases_ready(
                root_dir=root_dir,
                env=child_env,
                domains=parsed.domains,
                force_sync=parsed.force_db_sync,
            )
        )

    executable = shutil.which(cmd[0], path=child_env.get("PATH"))
    if executable is None:
        logger.error("command_executable_not_found", binary=cmd[0])
        return 127

    completed = subprocess.run(  # noqa: S603 - Executable resolved safely via shutil.which
        [executable, *cmd[1:]],
        cwd=root_dir,
        env=child_env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
