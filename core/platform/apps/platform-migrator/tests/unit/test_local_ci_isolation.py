"""Unit tests for clean-room test environment construction and affected-scope escalation."""

from __future__ import annotations

import json
from pathlib import Path

from ensure_test_databases import discover_test_database_targets, rewrite_database_env_vars
from run_in_test_env import (
    build_hermetic_test_environment,
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
    assert should_escalate_to_full_verification(["turbo.json"]) is True
    assert should_escalate_to_full_verification(["semgrep-architecture.yml"]) is True
