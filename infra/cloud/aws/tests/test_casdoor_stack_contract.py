"""Behavioral unit and cloud-architecture contract tests for the AWS Casdoor IdP stack."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

import pulumi
import pytest
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks
from pulumi.runtime.settings import SETTINGS
from pulumi.runtime.stack import run_pulumi_func

CASDOOR_STACK_DIR = str(Path(__file__).resolve().parents[1] / "casdoor")
if CASDOOR_STACK_DIR not in sys.path:
    sys.path.insert(0, CASDOOR_STACK_DIR)

from constants import CasdoorConstants, resolve_casdoor_version
from ecs import DB_INIT_SHELL_COMMAND, build_casdoor_container_definitions
from roles import provision_roles
from secret_resources import build_casdoor_postgres_dsn


class _CasdoorRolesMocks(Mocks):
    """Pulumi runtime mock capturing IAM RolePolicy documents created by provision_roles."""

    def __init__(self) -> None:
        self.role_policies: dict[str, dict[str, object]] = {}

    def new_resource(self, args: MockResourceArgs) -> tuple[str | None, dict[str, object]]:
        if args.typ == "aws:iam/rolePolicy:RolePolicy":
            raw_policy = args.inputs.get("policy")
            if isinstance(raw_policy, str):
                self.role_policies[args.name] = json.loads(raw_policy)
        return f"{args.name}-id", dict(args.inputs)

    def call(self, args: MockCallArgs) -> tuple[dict[str, object], list[tuple[str, str]] | None]:
        del args
        return {}, None


def _run_pulumi_test(mocks: Mocks, fn: Callable[[], pulumi.Output[None]]) -> None:
    async def _runner() -> None:
        SETTINGS.rpc_manager.clear()
        SETTINGS.outputs.clear()
        set_mocks(mocks, preview=True)
        await run_pulumi_func(lambda: fn().future())

    asyncio.run(_runner())


def test_resolve_casdoor_version_trims_valid_value_and_rejects_missing() -> None:
    assert resolve_casdoor_version({"CASDOOR_VERSION": "  v4.30.0  "}) == "v4.30.0"

    with pytest.raises(RuntimeError, match="CASDOOR_VERSION"):
        resolve_casdoor_version({})

    with pytest.raises(RuntimeError, match="CASDOOR_VERSION"):
        resolve_casdoor_version({"CASDOOR_VERSION": "   "})


def test_build_casdoor_postgres_dsn_uses_least_privilege_role_and_validates_inputs() -> None:
    assert (
        build_casdoor_postgres_dsn("db.internal:5432", "s3cr3t!")
        == "user=casdoor_app password=s3cr3t! host=db.internal port=5432 sslmode=require dbname=casdoor"
    )
    assert (
        build_casdoor_postgres_dsn("db.internal", "s3cr3t!")
        == "user=casdoor_app password=s3cr3t! host=db.internal port=5432 sslmode=require dbname=casdoor"
    )

    with pytest.raises(ValueError, match="host must not be empty"):
        build_casdoor_postgres_dsn(":5432", "s3cr3t!")

    with pytest.raises(ValueError, match="Invalid Casdoor PostgreSQL port"):
        build_casdoor_postgres_dsn("db.internal:notaport", "s3cr3t!")


def test_casdoor_container_defs_wire_least_privilege_db_init_and_firelens_sidecar() -> None:
    containers = build_casdoor_container_definitions(
        prefix="staging-",
        dsn_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:platform/staging-casdoor-dsn",
        db_password_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:platform/staging-casdoor-db-pwd",
        global_db_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:edi/staging-global-db",
        region_name="us-east-1",
        ecr_repo_url="123456789012.dkr.ecr.us-east-1.amazonaws.com/staging-casdoor-image",
        image_tag="v4.30.0",
        admin_pwd_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:platform/staging-casdoor-pwd",
        dns_domain="staging.flowwolf.io",
        firelens_endpoint="openobserve.staging.local:5080",
        obs_user_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:platform/staging-obs-user",
        obs_pass_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:platform/staging-obs-pass",
    )

    by_name = {c["name"]: c for c in containers}
    assert set(by_name) == {"casdoor-db-init", "casdoor", "log_router"}

    # DB init container must use pinned Postgres image, stdin `\gexec`, non-superuser role, and global_db isolation
    init_c = by_name["casdoor-db-init"]
    assert init_c["essential"] is False
    assert init_c["image"] == "public.ecr.aws/docker/library/postgres:15.10-alpine"
    assert init_c["command"] == ["sh", "-c", DB_INIT_SHELL_COMMAND]
    assert "ON_ERROR_STOP=1" in DB_INIT_SHELL_COMMAND
    assert "\\gexec" in DB_INIT_SHELL_COMMAND
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in DB_INIT_SHELL_COMMAND
    assert "GRANT %I TO %I" in DB_INIT_SHELL_COMMAND
    assert "REVOKE CONNECT ON DATABASE" in DB_INIT_SHELL_COMMAND
    assert " -c " not in DB_INIT_SHELL_COMMAND
    assert {s["name"] for s in init_c["secrets"]} == {
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "CASDOOR_DB_PASSWORD",
    }

    # Main Casdoor container must wait for DB init SUCCESS and NEVER receive RDS master secret
    app_c = by_name["casdoor"]
    assert app_c["essential"] is True
    assert (
        app_c["image"]
        == "123456789012.dkr.ecr.us-east-1.amazonaws.com/staging-casdoor-image:v4.30.0"
    )
    assert app_c["dependsOn"] == [
        {"containerName": CasdoorConstants.DB_INIT_CONTAINER_NAME, "condition": "SUCCESS"}
    ]
    assert {s["name"] for s in app_c["secrets"]} == {"dataSourceName", "initAdminPassword"}
    assert app_c["logConfiguration"]["logDriver"] == "awsfirelens"


def test_casdoor_container_defs_fall_back_to_awslogs_without_firelens() -> None:
    containers = build_casdoor_container_definitions(
        prefix="staging-",
        dsn_arn="arn:dsn",
        db_password_arn="arn:db-pwd",
        global_db_arn="arn:db",
        region_name="us-east-1",
        ecr_repo_url="123456789012.dkr.ecr.us-east-1.amazonaws.com/staging-casdoor-image",
        image_tag="v4.30.0",
        admin_pwd_arn="arn:pwd",
        dns_domain="staging.flowwolf.io",
    )
    by_name = {c["name"]: c for c in containers}
    assert set(by_name) == {"casdoor-db-init", "casdoor"}
    assert by_name["casdoor"]["logConfiguration"]["logDriver"] == "awslogs"


def test_casdoor_roles_enforce_scoped_logs_least_privilege_secrets_and_optional_exec() -> None:
    mocks = _CasdoorRolesMocks()

    def _program() -> pulumi.Output[None]:
        _, exec_role = provision_roles(
            "staging-",
            {"Environment": "staging"},
            dsn_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:casdoor-dsn",
            db_password_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:casdoor-db-pwd",
            admin_password_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:casdoor-pwd",
            global_db_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:global-db",
            region_name="us-east-1",
            account_id="123456789012",
            enable_execute_command=False,
            obs_user_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:obs-user",
            obs_password_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:obs-pass",
        )
        return exec_role.arn.apply(lambda _: None)

    _run_pulumi_test(mocks, _program)

    # Task role SSM exec policy must be omitted when enable_execute_command=False (prod default)
    assert "staging-casdoor-task-role-policy" not in mocks.role_policies

    policy = mocks.role_policies["staging-casdoor-exec-role-secrets-policy"]
    statements = policy["Statement"]
    assert isinstance(statements, list)

    log_stmt = next(
        stmt
        for stmt in statements
        if isinstance(stmt, dict) and stmt.get("Action") == ["logs:CreateLogGroup"]
    )
    assert (
        log_stmt["Resource"]
        == "arn:aws:logs:us-east-1:123456789012:log-group:/ecs/staging-casdoor*"
    )

    secret_stmt = next(
        stmt
        for stmt in statements
        if isinstance(stmt, dict) and stmt.get("Action") == ["secretsmanager:GetSecretValue"]
    )
    assert secret_stmt["Resource"] == [
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:casdoor-dsn",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:casdoor-db-pwd",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:casdoor-pwd",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:global-db",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:obs-user",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:obs-pass",
    ]
