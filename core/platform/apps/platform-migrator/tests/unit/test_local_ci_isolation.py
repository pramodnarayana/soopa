"""Unit tests for clean-room test environment construction and affected-scope escalation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from ensure_test_databases import (
    compute_schema_and_seed_fingerprint,
    discover_test_database_targets,
    filter_targets_for_active_domains,
    rewrite_database_env_vars,
)
from run_in_test_env import (
    build_hermetic_test_environment,
    build_interactive_test_environment,
    should_escalate_to_full_verification,
)


def test_rewrite_database_env_vars_rewrites_all_domain_and_shard_dsns_only() -> None:
    raw_env = {
        "DATABASE_URL": "postgresql://ucp_admin:ucp_password@localhost:5432/global_db",
        "GLOBAL_DATABASE_URL": "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/global_db",
        "EDI_DATABASE_URL": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "TEST_SHARD_DB_URL": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "SHARD_OVERRIDES__EDI_SHARD_1": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "BILLING_DATABASE_URL": "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard",
        "SHARD_OVERRIDES__BILLING_SHARD_1": "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard",
        "DATABASE__SHARD_OVERRIDES__BILLING_SHARD_1": "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard",
        "POSTGRES_DB": "zitadel",
        "IDENTITY_PLATFORM_ORG_ID": "384772010141548547",
    }

    rewritten = rewrite_database_env_vars(raw_env)

    assert (
        rewritten["DATABASE_URL"]
        == "postgresql://ucp_admin:ucp_password@localhost:5432/global_db_test"
    )
    assert (
        rewritten["GLOBAL_DATABASE_URL"]
        == "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/global_db_test"
    )
    assert (
        rewritten["EDI_DATABASE_URL"]
        == "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test"
    )
    assert (
        rewritten["TEST_SHARD_DB_URL"]
        == "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test"
    )
    assert (
        rewritten["SHARD_OVERRIDES__EDI_SHARD_1"]
        == "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test"
    )
    assert (
        rewritten["BILLING_DATABASE_URL"]
        == "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard_test"
    )
    assert (
        rewritten["SHARD_OVERRIDES__BILLING_SHARD_1"]
        == "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard_test"
    )
    assert (
        rewritten["DATABASE__SHARD_OVERRIDES__BILLING_SHARD_1"]
        == "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard_test"
    )
    assert rewritten["POSTGRES_DB"] == "zitadel"
    assert rewritten["IDENTITY_PLATFORM_ORG_ID"] == "384772010141548547"


def test_discover_test_database_targets_deduplicates_global_and_shards() -> None:
    env = {
        "DATABASE_URL": "postgresql://ucp_admin:ucp_password@localhost:5432/global_db_test",
        "EDI_DATABASE_URL": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test",
        "SHARD_OVERRIDES__EDI_SHARD_1": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test",
    }
    targets = discover_test_database_targets(env)
    assert [t.db_name for t in targets] == ["global_db_test", "edi_shard_test"]
    assert targets[0].is_global is True
    assert targets[1].is_global is False


def test_build_hermetic_test_environment_never_touches_dot_env_on_disk(
    tmp_path: Path,
) -> None:
    (tmp_path / "core" / "platform").mkdir(parents=True)
    (tmp_path / "core" / "platform" / "topology.json").write_text(
        json.dumps(
            {
                "topics": [{"name": "platform-events-topic", "fifo": True}],
                "queues": [{"name": "identity-jobs", "fifo": True}],
                "subscriptions": [],
                "buckets": [],
                "secrets": [],
            }
        ),
        encoding="utf-8",
    )

    dot_env = tmp_path / ".env"
    dot_env.write_text(
        "IDENTITY_PLATFORM_ORG_ID=397365687661625347\n"
        "SECRET_ONLY_IN_LOCAL_DOT_ENV=must_not_leak\n"
        "DATABASE_URL=postgresql://ucp_admin:ucp_password@localhost:5432/global_db\n",
        encoding="utf-8",
    )
    before_stat = dot_env.stat()
    before_bytes = dot_env.read_bytes()

    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text(
        "IDENTITY_PLATFORM_ORG_ID=384772010141548547\n"
        "DATABASE_URL=postgresql://ucp_admin:ucp_password@localhost:5432/global_db\n"
        "EDI_DATABASE_URL=postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard\n",
        encoding="utf-8",
    )

    ambient_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/dev",
        "SECRET_ONLY_IN_LOCAL_DOT_ENV": "ambient_leak",
        "IDENTITY_PLATFORM_ORG_ID": "397365687661625347",
        "AWS_PROFILE": "production-admin",
    }

    child_env = build_hermetic_test_environment(
        root_dir=tmp_path,
        env_file=dot_env_example,
        base_environ=ambient_env,
        domains="platform",
    )

    after_stat = dot_env.stat()
    assert after_stat.st_ino == before_stat.st_ino
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
    assert dot_env.read_bytes() == before_bytes

    assert child_env["SOOPA_ENV_FILE"] == str(dot_env_example)
    assert child_env["IDENTITY_PLATFORM_ORG_ID"] == "384772010141548547"
    assert (
        child_env["DATABASE_URL"]
        == "postgresql://ucp_admin:ucp_password@localhost:5432/global_db_test"
    )
    assert (
        child_env["EDI_DATABASE_URL"]
        == "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test"
    )
    assert child_env["AWS_SHARED_CREDENTIALS_FILE"] == "/dev/null"
    assert child_env["AWS_CONFIG_FILE"] == "/dev/null"
    assert "SECRET_ONLY_IN_LOCAL_DOT_ENV" not in child_env
    assert "AWS_PROFILE" not in child_env
    assert "SQS_IDENTITY_JOBS_QUEUE_URL" in child_env


def test_should_escalate_to_full_verification_on_root_configs() -> None:
    assert (
        should_escalate_to_full_verification(["core/ucp/packages/ucp/src/ucp/router.py"]) is False
    )
    assert (
        should_escalate_to_full_verification(
            ["apps/edi/packages/edi/src/edi/module.py", "README.md"]
        )
        is False
    )
    assert should_escalate_to_full_verification([".env.example"]) is True
    assert should_escalate_to_full_verification(["pyproject.toml"]) is True
    assert should_escalate_to_full_verification(["uv.lock"]) is True
    assert should_escalate_to_full_verification(["tach.toml"]) is True
    assert should_escalate_to_full_verification(["turbo.json"]) is True
    assert should_escalate_to_full_verification(["semgrep-architecture.yml"]) is True
    assert should_escalate_to_full_verification(["scripts/aggregate_coverage.py"]) is True
    assert should_escalate_to_full_verification(["infra/local/scripts/run_in_test_env.py"]) is True
    assert (
        should_escalate_to_full_verification(["infra/local/scripts/ensure_test_databases.py"])
        is True
    )
    assert should_escalate_to_full_verification(["infra/local/scripts/sync_topology.py"]) is True
    assert should_escalate_to_full_verification([".github/actions/setup-env/action.yml"]) is True
    assert should_escalate_to_full_verification([".github/workflows/ci.yml"]) is True
    assert should_escalate_to_full_verification([".semgrep/enterprise-rules.yml"]) is True


def test_should_not_escalate_on_local_utility_scripts_or_package_manifests() -> None:
    assert (
        should_escalate_to_full_verification(
            [
                "infra/local/scripts/reconcile_schema_drift.py",
                "infra/local/scripts/drop_schemas.py",
                "infra/local/scripts/print_credentials.py",
                "infra/local/scripts/clean_openas2.py",
                "infra/local/scripts/infra_reset.py",
            ]
        )
        is False
    )
    assert (
        should_escalate_to_full_verification(
            [
                "package.json",
                "pnpm-lock.yaml",
                "apps/ip/packages/ui/package.json",
                "apps/ip/scripts/seed.py",
            ]
        )
        is False
    )


def test_pre_commit_hook_runs_lightweight_staged_checks_only() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    pre_commit = (repo_root / ".husky" / "pre-commit").read_text(encoding="utf-8")

    assert "lint-staged" in pre_commit
    assert "docker ps" not in pre_commit
    assert "uvx pre-commit" not in pre_commit
    assert "turbo typecheck" not in pre_commit


def test_pre_push_hook_does_not_invoke_heavy_ci_verification() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    pre_push = (repo_root / ".husky" / "pre-push").read_text(encoding="utf-8")

    active_pre_push_lines = [
        line.strip()
        for line in pre_push.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any("verify_ci.sh" in line for line in active_pre_push_lines)


def test_ci_workflow_runs_parallel_distributed_integration_shards() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    ci_workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "test:integration:core" in ci_workflow
    assert "test:integration:edi" in ci_workflow
    assert "test:integration:ip" in ci_workflow
    assert "coverage-integration-${{ matrix.shard }}" in ci_workflow


def test_aggregate_coverage_stages_distributed_matrix_shard_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[6]
    script_path = repo_root / "scripts" / "aggregate_coverage.py"
    spec = importlib.util.spec_from_file_location("aggregate_coverage", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pkg_rel = Path("apps") / "ip" / "packages" / "ip"
    pkg_dir = tmp_path / pkg_rel
    pkg_dir.mkdir(parents=True)

    artifacts_dir = tmp_path / "coverage_artifacts"
    unit_src = artifacts_dir / "coverage-unit" / pkg_rel / ".coverage.unit"
    int_core_src = artifacts_dir / "coverage-integration-core" / pkg_rel / ".coverage.integration"
    int_ip_src = artifacts_dir / "coverage-integration-ip" / pkg_rel / ".coverage.integration"

    for artifact_file, content in (
        (unit_src, b"unit-shard"),
        (int_core_src, b"core-shard"),
        (int_ip_src, b"ip-shard"),
    ):
        artifact_file.parent.mkdir(parents=True, exist_ok=True)
        artifact_file.write_bytes(content)

    prepared = module.prepare_coverage_inputs(str(pkg_dir), str(artifacts_dir), str(tmp_path))
    assert prepared is True

    staged_files = sorted(p.name for p in pkg_dir.glob(".coverage.*"))
    assert len(staged_files) == 3
    staged_payloads = {p.read_bytes() for p in pkg_dir.glob(".coverage.*")}
    assert staged_payloads == {b"unit-shard", b"core-shard", b"ip-shard"}


def test_aggregate_coverage_purges_stale_shard_and_local_files_before_staging(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[6]
    script_path = repo_root / "scripts" / "aggregate_coverage.py"
    spec = importlib.util.spec_from_file_location("aggregate_coverage", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pkg_rel = Path("apps") / "ip" / "packages" / "ip"
    pkg_dir = tmp_path / pkg_rel
    pkg_dir.mkdir(parents=True)
    (pkg_dir / ".coverage.shard_99").write_bytes(b"stale-shard-99")
    (pkg_dir / ".coverage.local_unit").write_bytes(b"stale-local-unit")

    artifacts_dir = tmp_path / "coverage_artifacts"
    fresh_src = artifacts_dir / "coverage-unit" / pkg_rel / ".coverage.unit"
    fresh_src.parent.mkdir(parents=True, exist_ok=True)
    fresh_src.write_bytes(b"fresh-unit")

    prepared = module.prepare_coverage_inputs(str(pkg_dir), str(artifacts_dir), str(tmp_path))
    assert prepared is True

    staged_files = [p.name for p in pkg_dir.glob(".coverage.*")]
    assert staged_files == [".coverage.shard_1"]
    assert (pkg_dir / ".coverage.shard_1").read_bytes() == b"fresh-unit"


def test_verify_ci_enforces_enterprise_semgrep_and_scripts_static_checks() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    verify_ci = (repo_root / "scripts" / "verify_ci.sh").read_text(encoding="utf-8")
    ci_workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    expected_script_mypy = (
        "mypy --explicit-package-bases infra/local/scripts/run_in_test_env.py "
        "infra/local/scripts/ensure_test_databases.py "
        "infra/local/scripts/sync_topology.py "
        "scripts/aggregate_coverage.py"
    )
    assert "--config=.semgrep/enterprise-rules.yml" in verify_ci
    assert "ruff check apps core infra/local/scripts scripts" in verify_ci
    assert expected_script_mypy in verify_ci
    assert "ruff check apps core infra/local/scripts scripts" in ci_workflow
    assert expected_script_mypy in ci_workflow


def test_rewrite_and_discover_support_driver_qualified_postgres_and_reject_empty_db_name() -> None:
    env = {
        "DATABASE_URL": "postgresql+psycopg2://ucp_admin:ucp_password@localhost:5432/global_db",
        "OPTIONAL_DATABASE_URL": "",
        "SQLITE_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    }
    rewritten = rewrite_database_env_vars(env)
    assert (
        rewritten["DATABASE_URL"]
        == "postgresql+psycopg2://ucp_admin:ucp_password@localhost:5432/global_db_test"
    )
    assert rewritten["OPTIONAL_DATABASE_URL"] == ""
    assert rewritten["SQLITE_DATABASE_URL"] == "sqlite+aiosqlite:///:memory:"

    targets = discover_test_database_targets(env)
    assert len(targets) == 1
    assert targets[0].db_name == "global_db_test"
    assert targets[0].dsn == "postgresql://ucp_admin:ucp_password@localhost:5432/global_db_test"

    with pytest.raises(ValueError, match="missing a database name"):
        rewrite_database_env_vars(
            {"DATABASE_URL": "postgresql+psycopg2://ucp_admin:ucp_password@localhost:5432/"}
        )


def test_filter_targets_for_active_domains_excludes_inactive_shards() -> None:
    raw_env = {
        "DATABASE_URL": "postgresql://ucp_admin:ucp_password@localhost:5432/global_db",
        "EDI_DATABASE_URL": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "TEST_SHARD_DB_URL": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "SHARD_OVERRIDES__EDI_SHARD_1": "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "BILLING_DATABASE_URL": "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard",
        "SHARD_OVERRIDES__BILLING_SHARD_1": "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard",
    }
    rewritten = rewrite_database_env_vars(raw_env)
    all_targets = discover_test_database_targets(rewritten)

    edi_only = filter_targets_for_active_domains(
        all_targets, rewritten, ["edi"], domains_arg="platform,edi"
    )
    assert [t.db_name for t in edi_only] == ["global_db_test", "edi_shard_test"]

    billing_only = filter_targets_for_active_domains(
        all_targets, rewritten, ["billing"], domains_arg="platform,billing"
    )
    assert [t.db_name for t in billing_only] == ["global_db_test", "billing_shard_test"]

    platform_only = filter_targets_for_active_domains(
        all_targets, rewritten, [], domains_arg="platform"
    )
    assert [t.db_name for t in platform_only] == ["global_db_test"]


def test_build_interactive_test_environment_overrides_inherited_soopa_env_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "core" / "platform").mkdir(parents=True)
    (tmp_path / "core" / "platform" / "topology.json").write_text(
        json.dumps(
            {
                "topics": [],
                "queues": [],
                "subscriptions": [],
                "buckets": [],
                "secrets": [],
            }
        ),
        encoding="utf-8",
    )
    explicit_env = tmp_path / ".env.custom"
    explicit_env.write_text(
        "DATABASE_URL=postgresql://ucp_admin:ucp_password@localhost:5432/global_db\n",
        encoding="utf-8",
    )

    child_env = build_interactive_test_environment(
        root_dir=tmp_path,
        env_file=explicit_env,
        base_environ={"SOOPA_ENV_FILE": "/stale/inherited/.env"},
        domains="platform",
    )
    assert child_env["SOOPA_ENV_FILE"] == str(explicit_env)


def test_compute_schema_and_seed_fingerprint_ignores_node_modules_seed_scripts(
    tmp_path: Path,
) -> None:
    real_seed = tmp_path / "apps" / "edi" / "scripts" / "seed_jobs.py"
    real_seed.parent.mkdir(parents=True)
    real_seed.write_text("# canonical seed\n", encoding="utf-8")
    (tmp_path / "core" / "platform" / "packages" / "database" / "migrations").mkdir(parents=True)

    env = {"DATABASE_URL": "postgresql://ucp_admin:ucp_password@localhost:5432/global_db_test"}
    baseline = compute_schema_and_seed_fingerprint(tmp_path, env, ["edi"])

    vendored_seed = (
        tmp_path
        / "apps"
        / "edi"
        / "apps"
        / "edi-delivery-worker"
        / "node_modules"
        / "@soopa"
        / ".ignored_api"
        / "scripts"
        / "seed.py"
    )
    vendored_seed.parent.mkdir(parents=True)
    vendored_seed.write_text("# transient pnpm artifact\n", encoding="utf-8")

    after_node_modules = compute_schema_and_seed_fingerprint(tmp_path, env, ["edi"])
    assert after_node_modules == baseline
