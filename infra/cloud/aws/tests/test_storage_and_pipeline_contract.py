"""Unit and architectural contract tests for S3 storage primitives and CI/CD segregation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pulumi
import pytest
from infra_seedwork.storage import build_account_scoped_bucket_name, provision_secure_bucket
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks
from pulumi.runtime.settings import SETTINGS
from pulumi.runtime.stack import run_pulumi_func

AWS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AWS_ROOT.parents[2]


def _run_pulumi_test(fn: Callable[[], pulumi.Output[None]]) -> None:
    async def _runner() -> None:
        SETTINGS.rpc_manager.clear()
        SETTINGS.outputs.clear()
        await run_pulumi_func(lambda: fn().future())

    asyncio.run(_runner())


class _StorageTestMocks(Mocks):
    def new_resource(self, args: MockResourceArgs) -> tuple[str | None, dict[str, object]]:
        if args.typ == "aws:s3/bucketV2:BucketV2":
            bucket_name = str(args.inputs.get("bucket", args.name))
            return f"{args.name}-id", {
                **args.inputs,
                "id": bucket_name,
                "bucket": bucket_name,
                "arn": f"arn:aws:s3:::{bucket_name}",
            }
        return f"{args.name}-id", dict(args.inputs)

    def call(self, args: MockCallArgs) -> tuple[dict[str, object], list[tuple[str, str]]]:
        if args.token == "aws:index/getCallerIdentity:getCallerIdentity":
            return (
                {
                    "accountId": "634680389104",
                    "arn": "arn:aws:iam::634680389104:role/deployer",
                    "userId": "AROAEXAMPLE",
                },
                [],
            )
        return ({}, [])


def test_build_account_scoped_bucket_name_appends_account_id_idempotently() -> None:
    """Ensure S3 bucket names are deterministically scoped to the AWS Account ID."""
    assert (
        build_account_scoped_bucket_name("staging-edi-as2-payloads", "634680389104")
        == "staging-edi-as2-payloads-634680389104"
    )
    assert (
        build_account_scoped_bucket_name("staging-edi-as2-payloads-634680389104", "634680389104")
        == "staging-edi-as2-payloads-634680389104"
    )


@pytest.mark.parametrize(
    ("logical_name", "account_id"),
    [
        ("", "634680389104"),
        ("staging-edi-as2-payloads", ""),
        ("staging-edi-as2-payloads", "not-numeric"),
        ("a" * 55, "634680389104"),  # exceeds 63-char S3 DNS limit
    ],
)
def test_build_account_scoped_bucket_name_rejects_invalid_inputs(
    logical_name: str, account_id: str
) -> None:
    """Fail fast on invalid AWS account IDs or bucket names exceeding S3 63-char limit."""
    with pytest.raises(ValueError):
        build_account_scoped_bucket_name(logical_name, account_id)


def test_provision_secure_bucket_scopes_physical_bucket_to_caller_account() -> None:
    """Verify provision_secure_bucket defaults physical S3 bucket name to <name>-<account_id>."""

    def _verify() -> pulumi.Output[None]:
        set_mocks(_StorageTestMocks(), project="edi-storage", stack="staging", preview=True)
        bucket = provision_secure_bucket(
            name="staging-edi-as2-payloads",
            tags={"Environment": "staging"},
        )

        def _assert(pair: list[str]) -> None:
            bucket_name, bucket_arn = pair[0], pair[1]
            assert bucket_name == "staging-edi-as2-payloads-634680389104"
            assert bucket_arn == "arn:aws:s3:::staging-edi-as2-payloads-634680389104"

        return pulumi.Output.all(bucket.bucket, bucket.arn).apply(_assert)

    _run_pulumi_test(_verify)


def test_edi_as2_stack_wires_s3_bucket_env_and_iam_permissions() -> None:
    """Ensure edi/as2 stack injects S3_BUCKET and least-privilege S3 permissions from edi-storage."""
    as2_source = (AWS_ROOT / "apps" / "edi" / "as2" / "__main__.py").read_text(encoding="utf-8")
    assert (
        'as2_payloads_bucket_name = storage.require_output("as2_payloads_bucket_name")'
        in as2_source
    )
    assert (
        'as2_payloads_bucket_arn = storage.require_output("as2_payloads_bucket_arn")' in as2_source
    )
    assert '"S3_BUCKET"' in as2_source
    assert '"s3:PutObject"' in as2_source
    assert '"s3:GetObject"' in as2_source
    assert '"s3:ListBucket"' in as2_source


def test_stateful_vs_stateless_cicd_pipeline_segregation_and_break_glass_refresh() -> None:
    """Enforce strict separation between Stateful Infra workflows and Stateless App workflows."""
    stateful_stacks = [
        "infra/cloud/aws/apps/ucp/messaging",
        "infra/cloud/aws/apps/identity/messaging",
        "infra/cloud/aws/apps/notification/messaging",
        "infra/cloud/aws/apps/edi/messaging",
        "infra/cloud/aws/apps/edi/storage",
    ]
    stateless_compute_stacks = [
        "infra/cloud/aws/platform/migrator",
        "infra/cloud/aws/apps/edi/migrator",
        "infra/cloud/aws/apps/api",
        "infra/cloud/aws/apps/ucp/workers",
        "infra/cloud/aws/apps/edi/workers",
        "infra/cloud/aws/apps/edi/as2",
    ]

    infra_workflows = [
        REPO_ROOT / ".github" / "workflows" / "preview-infra.yml",
        REPO_ROOT / ".github" / "workflows" / "provision-infra.yml",
    ]
    for wf in infra_workflows:
        content = wf.read_text(encoding="utf-8")
        platform_pos = content.index("stack-dir: infra/cloud/aws/platform")
        for stack in stateful_stacks:
            marker = f"stack-dir: {stack}"
            assert marker in content, f"{wf.name} must manage stateful stack '{stack}'"
            assert content.index(marker) > platform_pos, (
                f"{wf.name} must run '{stack}' after 'infra/cloud/aws/platform'"
            )
        for stack in stateless_compute_stacks:
            assert f"stack-dir: {stack}" not in content, (
                f"{wf.name} must not deploy stateless compute stack '{stack}'"
            )

    app_workflows = [
        REPO_ROOT / ".github" / "workflows" / "preview-app-iac.yml",
        REPO_ROOT / ".github" / "workflows" / "deploy.yml",
    ]
    for wf in app_workflows:
        content = wf.read_text(encoding="utf-8")
        for stack in stateless_compute_stacks:
            assert f"stack-dir: {stack}" in content, (
                f"{wf.name} must manage stateless stack '{stack}'"
            )
        for stack in stateful_stacks:
            assert f"stack-dir: {stack}" not in content, (
                f"{wf.name} must not touch stateful messaging/storage stack '{stack}'"
            )

    # Break-glass refresh policy: never hardcoded `refresh: "true"`, wired via REFRESH_STATE
    for rollout_wf in [
        REPO_ROOT / ".github" / "workflows" / "provision-infra.yml",
        REPO_ROOT / ".github" / "workflows" / "deploy.yml",
    ]:
        content = rollout_wf.read_text(encoding="utf-8")
        assert 'refresh: "true"' not in content
        assert "refresh: true" not in content
        assert "REFRESH_STATE:" in content
        assert "refresh: ${{ env.REFRESH_STATE }}" in content
