"""Contract and unit tests for topology-driven SQS IAM ARN resolution."""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
from collections.abc import Callable
from pathlib import Path

import pulumi
import pytest
from infra_seedwork.messaging import (
    TopologyConfig,
    build_database_pubsub_env_vars,
    merge_messaging_queue_arns,
    provision_from_topology,
    resolve_messaging_queue_arns,
    select_messaging_queue_arns,
    sqs_arns_from_queue_env_vars,
    sqs_url_to_arn,
)
from infra_seedwork.topology import load_topology
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks
from pulumi.runtime.settings import SETTINGS
from pulumi.runtime.stack import run_pulumi_func

AWS_ROOT = Path(__file__).resolve().parents[1]


def _run_pulumi_test(fn: Callable[[], pulumi.Output[None]]) -> None:
    async def _runner() -> None:
        SETTINGS.rpc_manager.clear()
        SETTINGS.outputs.clear()
        await run_pulumi_func(lambda: fn().future())

    asyncio.run(_runner())


class _TopologyTestMocks(Mocks):
    """Pulumi test runtime mocks simulating pre- and post-rollout StackReferences."""

    def __init__(self, stack_outputs: dict[str, dict[str, object]] | None = None) -> None:
        self._stack_outputs = stack_outputs or {}

    def new_resource(self, args: MockResourceArgs) -> tuple[str | None, dict[str, object]]:
        if args.typ == "pulumi:pulumi:StackReference":
            stack_name = str(args.inputs.get("name", args.name))
            return stack_name, {
                "name": stack_name,
                "outputs": self._stack_outputs.get(stack_name, {}),
                "secretOutputNames": [],
            }
        physical_name = str(args.inputs.get("name", args.name))
        if args.typ == "aws:sqs/queue:Queue":
            return f"{args.name}-id", {
                **args.inputs,
                "arn": f"arn:aws:sqs:us-east-1:634680389104:{physical_name}",
                "url": f"https://sqs.us-east-1.amazonaws.com/634680389104/{physical_name}",
            }
        if args.typ == "aws:sns/topic:Topic":
            return f"{args.name}-id", {
                **args.inputs,
                "arn": f"arn:aws:sns:us-east-1:634680389104:{physical_name}",
            }
        return f"{args.name}-id", dict(args.inputs)

    def call(self, args: MockCallArgs) -> tuple[dict[str, object], list[tuple[str, str]]]:
        if args.token == "aws:index/getRegion:getRegion":
            return ({"name": "us-east-1", "id": "us-east-1"}, [])
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


def test_sqs_url_to_arn_converts_standard_fifo_and_govcloud_urls() -> None:
    """Verify deterministic conversion from AWS SQS Queue URLs to IAM Queue ARNs."""
    assert (
        sqs_url_to_arn("https://sqs.us-east-1.amazonaws.com/634680389104/staging-edi-edi-deliver")
        == "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver"
    )
    assert (
        sqs_url_to_arn(
            "https://sqs.us-east-1.amazonaws.com/634680389104/staging-notification-notifications.fifo"
        )
        == "arn:aws:sqs:us-east-1:634680389104:staging-notification-notifications.fifo"
    )
    assert (
        sqs_url_to_arn("https://sqs.us-gov-west-1.amazonaws.com/123456789012/gov-events.fifo")
        == "arn:aws-us-gov:sqs:us-gov-west-1:123456789012:gov-events.fifo"
    )


@pytest.mark.parametrize(
    "invalid_url",
    [
        "",
        "https://s3.us-east-1.amazonaws.com/bucket/key",
        "https://sqs.us-east-1.amazonaws.com/only-one-segment",
        "not-a-url",
    ],
)
def test_sqs_url_to_arn_rejects_malformed_urls(invalid_url: str) -> None:
    """Fail fast on invalid or non-SQS URLs rather than producing malformed IAM ARNs."""
    with pytest.raises(ValueError, match="Invalid AWS SQS queue URL"):
        sqs_url_to_arn(invalid_url)


def test_sqs_arns_from_queue_env_vars_filters_sns_topics_and_deduplicates() -> None:
    """Extract sorted SQS ARNs (including DLQ URLs) while ignoring SNS topic ARNs."""
    env_vars = {
        "SQS_NOTIFICATION_JOBS_QUEUE_URL": (
            "https://sqs.us-east-1.amazonaws.com/634680389104/staging-notification-notification-jobs.fifo"
        ),
        "SQS_DELIVER_QUEUE_URL": (
            "https://sqs.us-east-1.amazonaws.com/634680389104/staging-edi-edi-deliver"
        ),
        "SQS_DELIVER_DLQ_URL": (
            "https://sqs.us-east-1.amazonaws.com/634680389104/staging-edi-edi-deliver-dlq"
        ),
        "SQS_ALIAS_URL": (
            "https://sqs.us-east-1.amazonaws.com/634680389104/staging-edi-edi-deliver"
        ),
        "SNS_PLATFORM_EVENTS_TOPIC_ARN": (
            "arn:aws:sns:us-east-1:634680389104:staging-platform-events-topic.fifo"
        ),
    }

    assert sqs_arns_from_queue_env_vars(env_vars) == [
        "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver",
        "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver-dlq",
        "arn:aws:sqs:us-east-1:634680389104:staging-notification-notification-jobs.fifo",
    ]


def test_select_messaging_queue_arns_prefers_exported_arns_with_preview_fallback() -> None:
    """Steady state uses exported queue_arns; speculative PR preview falls back to queue_env_vars."""
    env_vars = {
        "SQS_EMAIL_CHANNEL_QUEUE_URL": (
            "https://sqs.us-east-1.amazonaws.com/634680389104/staging-notification-email-channel.fifo"
        ),
    }
    exported_arns = [
        "arn:aws:sqs:us-east-1:634680389104:staging-notification-notifications.fifo",
        "arn:aws:sqs:us-east-1:634680389104:staging-notification-email-channel.fifo",
    ]

    # Post-deploy steady state: uses exact exported queue_arns
    assert select_messaging_queue_arns(exported_arns, env_vars) == [
        "arn:aws:sqs:us-east-1:634680389104:staging-notification-email-channel.fifo",
        "arn:aws:sqs:us-east-1:634680389104:staging-notification-notifications.fifo",
    ]

    # Speculative PR preview before messaging stack rollout: falls back to queue_env_vars
    assert select_messaging_queue_arns(None, env_vars) == [
        "arn:aws:sqs:us-east-1:634680389104:staging-notification-email-channel.fifo",
    ]


def test_provision_from_topology_populates_queue_arns_including_consumed_dlqs() -> None:
    """Verify TopologyOutput.queue_arns includes provisioned queues and consumed DLQs."""
    topology: TopologyConfig = {
        "topics": [
            {
                "name": "platform-events-topic",
                "fifo": True,
                "env_var": "SNS_PLATFORM_EVENTS_TOPIC_ARN",
            }
        ],
        "queues": [
            {
                "name": "notifications",
                "fifo": True,
                "dlq": True,
                "env_var": "SQS_NOTIFICATION_QUEUE_URL",
            },
            {
                "name": "edi-deliver",
                "fifo": False,
                "dlq": True,
                "env_var": "SQS_DELIVER_QUEUE_URL",
                "dlq_env_var": "SQS_DELIVER_DLQ_URL",
            },
        ],
        "subscriptions": [],
    }

    def _verify() -> pulumi.Output[None]:
        set_mocks(_TopologyTestMocks(), project="test-messaging", stack="staging", preview=True)
        output = provision_from_topology(
            topology=topology,
            prefix="staging-",
            tags={"Environment": "staging"},
        )

        def _assert(arns: list[str]) -> None:
            assert arns == [
                "arn:aws:sqs:us-east-1:634680389104:staging-edi-deliver",
                "arn:aws:sqs:us-east-1:634680389104:staging-edi-deliver-dlq",
                "arn:aws:sqs:us-east-1:634680389104:staging-notifications.fifo",
            ]

        return output.queue_arns.apply(_assert)

    _run_pulumi_test(_verify)


def test_resolve_and_merge_messaging_queue_arns_survives_pre_rollout_preview() -> None:
    """Reproduce PR speculative preview where notification stack lacks queue_arns in S3 state."""

    def _verify() -> pulumi.Output[None]:
        set_mocks(
            _TopologyTestMocks(
                stack_outputs={
                    # Pre-rollout state: no `queue_arns` or `notification_queue_arn` in state yet!
                    "organization/notification/staging": {
                        "queue_env_vars": {
                            "SQS_EMAIL_CHANNEL_QUEUE_URL": (
                                "https://sqs.us-east-1.amazonaws.com/634680389104/"
                                "staging-notification-email-channel.fifo"
                            ),
                            "SQS_NOTIFICATION_JOBS_QUEUE_URL": (
                                "https://sqs.us-east-1.amazonaws.com/634680389104/"
                                "staging-notification-notification-jobs.fifo"
                            ),
                        }
                    },
                    # Post-rollout state: `queue_arns` already exported!
                    "organization/edi-messaging/staging": {
                        "queue_arns": [
                            "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver",
                            "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver-dlq",
                        ],
                        "queue_env_vars": {},
                    },
                }
            ),
            project="test-workers",
            stack="staging",
            preview=True,
        )
        notification_ref = pulumi.StackReference("organization/notification/staging")
        edi_ref = pulumi.StackReference("organization/edi-messaging/staging")

        single_resolved = resolve_messaging_queue_arns(notification_ref)
        merged_resolved = merge_messaging_queue_arns(notification_ref, edi_ref)

        def _assert(pair: list[list[str]]) -> None:
            notif_arns, all_arns = pair[0], pair[1]
            assert notif_arns == [
                "arn:aws:sqs:us-east-1:634680389104:staging-notification-email-channel.fifo",
                "arn:aws:sqs:us-east-1:634680389104:staging-notification-notification-jobs.fifo",
            ]
            assert all_arns == [
                "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver",
                "arn:aws:sqs:us-east-1:634680389104:staging-edi-edi-deliver-dlq",
                "arn:aws:sqs:us-east-1:634680389104:staging-notification-email-channel.fifo",
                "arn:aws:sqs:us-east-1:634680389104:staging-notification-notification-jobs.fifo",
            ]

        return pulumi.Output.all(single_resolved, merged_resolved).apply(_assert)

    _run_pulumi_test(_verify)


def test_build_database_pubsub_env_vars_maps_queues_dlqs_and_topics_with_filters() -> None:
    """Verify cloud-agnostic PostgreSQL Pub/Sub URI builder respects filters and suffixes."""
    topology: TopologyConfig = {
        "topics": [
            {
                "name": "platform-events-topic",
                "fifo": True,
                "env_var": "SNS_PLATFORM_EVENTS_TOPIC_ARN",
            },
            {
                "name": "ip-events-topic",
                "fifo": True,
                "env_var": "SNS_IP_EVENTS_TOPIC_ARN",
            },
        ],
        "queues": [
            {
                "name": "notifications",
                "fifo": True,
                "dlq": True,
                "env_var": "SQS_NOTIFICATION_QUEUE_URL",
            },
            {
                "name": "edi-deliver",
                "fifo": False,
                "dlq": True,
                "env_var": "SQS_DELIVER_QUEUE_URL",
                "dlq_env_var": "SQS_DELIVER_DLQ_URL",
            },
        ],
        "subscriptions": [],
    }

    full_env = build_database_pubsub_env_vars(topology)
    assert full_env == {
        "PUBSUB_TRANSPORT": "db",
        "SQS_NOTIFICATION_QUEUE_URL": "db://notifications.fifo",
        "SQS_DELIVER_QUEUE_URL": "db://edi-deliver",
        "SQS_DELIVER_DLQ_URL": "db://edi-deliver-dlq",
        "SNS_PLATFORM_EVENTS_TOPIC_ARN": "db://topic/platform-events-topic",
        "SNS_IP_EVENTS_TOPIC_ARN": "db://topic/ip-events-topic",
    }

    filtered_env = build_database_pubsub_env_vars(
        topology,
        queue_filter={"notifications"},
        topic_filter=set(),
    )
    assert filtered_env == {
        "PUBSUB_TRANSPORT": "db",
        "SQS_NOTIFICATION_QUEUE_URL": "db://notifications.fifo",
    }


def test_build_database_pubsub_env_vars_rejects_duplicate_env_vars() -> None:
    """Fail fast when topology declares duplicate env_var keys."""
    duplicate_topology: TopologyConfig = {
        "topics": [],
        "queues": [
            {"name": "q1", "fifo": False, "env_var": "SQS_DUPLICATE_URL"},
            {"name": "q2", "fifo": True, "env_var": "SQS_DUPLICATE_URL"},
        ],
    }
    with pytest.raises(ValueError, match="Duplicate env_var 'SQS_DUPLICATE_URL'"):
        build_database_pubsub_env_vars(duplicate_topology)


def test_build_database_pubsub_env_vars_against_canonical_topology() -> None:
    """Verify real infra/topology.json produces only db:// and db://topic/ URIs."""
    env_vars = build_database_pubsub_env_vars(load_topology())
    assert env_vars["PUBSUB_TRANSPORT"] == "db"
    assert env_vars["SNS_PLATFORM_EVENTS_TOPIC_ARN"] == "db://topic/platform-events-topic"
    assert env_vars["SQS_NOTIFICATION_QUEUE_URL"] == "db://notifications.fifo"
    for key, value in env_vars.items():
        if key == "PUBSUB_TRANSPORT":
            continue
        assert value.startswith("db://"), f"{key} must use db:// transport, got {value!r}"


def test_compute_and_messaging_stacks_enforce_zero_aws_sqs_sns_contract() -> None:
    """Enforce zero AWS SQS/SNS provisioning, IAM permissions, or messaging StackReferences."""
    messaging_stacks = [
        AWS_ROOT / "apps" / "ucp" / "messaging" / "__main__.py",
        AWS_ROOT / "apps" / "identity" / "messaging" / "__main__.py",
        AWS_ROOT / "apps" / "notification" / "messaging" / "__main__.py",
        AWS_ROOT / "apps" / "edi" / "messaging" / "__main__.py",
    ]
    for stack_file in messaging_stacks:
        source = stack_file.read_text(encoding="utf-8")
        assert "provision_from_topology" not in source, (
            f"{stack_file} must not provision AWS SQS/SNS resources via provision_from_topology"
        )
        assert "aws.sqs." not in source and "aws.sns." not in source, (
            f"{stack_file} must remain a zero-resource retired teardown stack"
        )
        assert "build_database_pubsub_env_vars" in source, (
            f"{stack_file} must build db:// queue_env_vars from topology.json"
        )
        assert 'pulumi.export("queue_env_vars", queue_env_vars)' in source
        assert 'pulumi.export("queue_arns", [])' in source

    platform_source = (AWS_ROOT / "platform" / "__main__.py").read_text(encoding="utf-8")
    assert "from event_bus import" not in platform_source
    assert "provision_event_bus(" not in platform_source
    assert 'platform_events_topic_uri = "db://topic/platform-events-topic"' in platform_source

    compute_stacks = [
        AWS_ROOT / "apps" / "ucp" / "workers" / "__main__.py",
        AWS_ROOT / "apps" / "edi" / "workers" / "__main__.py",
        AWS_ROOT / "apps" / "edi" / "as2" / "__main__.py",
        AWS_ROOT / "apps" / "api" / "__main__.py",
        AWS_ROOT / "platform" / "migrator" / "__main__.py",
    ]
    for stack_file in compute_stacks:
        source = stack_file.read_text(encoding="utf-8")
        assert "build_database_pubsub_env_vars" in source, (
            f"{stack_file} must inject PostgreSQL Pub/Sub URIs via build_database_pubsub_env_vars"
        )
        assert "sqs:" not in source, f"{stack_file} must not grant any sqs:* IAM permissions"
        assert "sns:" not in source, f"{stack_file} must not grant any sns:* IAM permissions"
        assert "-messaging/" not in source, (
            f"{stack_file} must not depend on retired *-messaging StackReferences"
        )
        tree = ast.parse(source, filename=str(stack_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "require_output"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                output_key = node.args[0].value
                assert not (
                    output_key.endswith("_queue_arn")
                    or output_key.startswith("sqs_")
                    or output_key == "queue_env_vars"
                    or output_key == "sns_platform_events_topic_arn"
                ), f"{stack_file} must not call require_output({output_key!r}) for legacy SQS/SNS"


def test_aws_compute_stacks_wire_dynamic_watch_base_url_and_secret_token() -> None:
    """Enforce that AWS API & worker stacks inject CONFIG_SYNC_INTERNAL_TOKEN and CONFIG_WATCH_BASE_URL."""
    platform_source = (AWS_ROOT / "platform" / "__main__.py").read_text(encoding="utf-8")
    assert '"config_sync_internal_token"' in platform_source

    for rel in (
        "apps/api/__main__.py",
        "apps/ucp/workers/__main__.py",
        "apps/edi/workers/__main__.py",
    ):
        source = (AWS_ROOT / rel).read_text(encoding="utf-8")
        assert '"CONFIG_SYNC_INTERNAL_TOKEN"' in source, (
            f"{rel} must inject CONFIG_SYNC_INTERNAL_TOKEN"
        )
        assert ":config_sync_internal_token::" in source, (
            f"{rel} must pull CONFIG_SYNC_INTERNAL_TOKEN from Secrets Manager"
        )
        assert '"ENV"' in source, f"{rel} must inject ENV alongside ENVIRONMENT"

    for rel in ("apps/ucp/workers/__main__.py", "apps/edi/workers/__main__.py"):
        source = (AWS_ROOT / rel).read_text(encoding="utf-8")
        assert '"CONFIG_WATCH_BASE_URL"' in source, f"{rel} must inject CONFIG_WATCH_BASE_URL"


def test_config_watch_gateway_foundation_endpoints_and_staging_reconcile_contracts() -> None:
    """Enforce dedicated config-watch-gateway Fargate service, retired SNS/SQS VPC endpoints, and Staging schema reconcile."""
    api_source = (AWS_ROOT / "apps" / "api" / "__main__.py").read_text(encoding="utf-8")
    assert "config-watch-gateway" in api_source
    assert "unified_api.watch_gateway:app" in api_source
    assert 'path_pattern="/api/v1/internal/*/config/*"' in api_source
    assert "priority=190" in api_source
    assert 'cpu="256"' in api_source
    assert 'memory="512"' in api_source
    assert "port=8081" in api_source
    assert "deregistration_delay=30" in api_source
    assert api_source.count("autoscaling_config=autoscaling_config") >= 2

    foundation_source = (AWS_ROOT / "foundation" / "__main__.py").read_text(encoding="utf-8")
    assert '"sns"' not in foundation_source
    assert '"sqs"' not in foundation_source
    assert '["logs", "secretsmanager"]' in foundation_source

    repo_root = AWS_ROOT.parents[2]
    deploy_source = (repo_root / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    migrate_idx = deploy_source.index("python -m platform_migrator migrate --domain platform")
    reconcile_idx = deploy_source.index(
        "python infra/local/scripts/reconcile_schema_drift.py --domain platform --skip-dotenv"
    )
    seed_idx = deploy_source.index("python -m platform_migrator seed --domain platform")
    assert migrate_idx < reconcile_idx < seed_idx, (
        "deploy.yml must reconcile global_db schema drift after migrate and before seed"
    )


def test_platform_migrator_topic_and_api_casdoor_audience_contracts() -> None:
    """Enforce platform/migrator DB Pub/Sub topic injection and API multi-audience Casdoor wiring."""
    migrator_source = (AWS_ROOT / "platform" / "migrator" / "__main__.py").read_text(
        encoding="utf-8"
    )
    assert 'topic_filter={"platform-events-topic"}' in migrator_source
    assert "queue_env_vars_to_ecs_format(pubsub_env_vars, {})" in migrator_source
    assert '"IDENTITY_ISSUER"' in migrator_source
    assert 'require_output("identity_domain")' in migrator_source

    api_source = (AWS_ROOT / "apps" / "api" / "__main__.py").read_text(encoding="utf-8")
    assert ":identity_audience::" in api_source
    assert "platform_admin_domains" in api_source

    staging_cfg = (AWS_ROOT / "apps" / "api" / "Pulumi.staging.yaml").read_text(encoding="utf-8")
    assert "api:platform_admin_domains: flowwolf.io" in staging_cfg


def test_all_aws_stacks_import_existing_infra_seedwork_symbols() -> None:
    """Verify every `from infra_seedwork.* import ...` across all AWS stacks resolves cleanly."""
    excluded_dirs = {
        ".venv",
        "venv",
        ".pytest_cache",
        "__pycache__",
        "packages",
        "tests",
        "node_modules",
    }
    stack_files: list[Path] = []
    for root, dirs, files in os.walk(AWS_ROOT):
        root_path = Path(root)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in excluded_dirs
            and not d.startswith(".")
            and not d.endswith(".egg-info")
            and not (root_path / d / "pyvenv.cfg").exists()
        )
        for filename in sorted(files):
            if filename.endswith(".py"):
                stack_files.append(root_path / filename)

    assert stack_files
    for stack_file in stack_files:
        tree = ast.parse(stack_file.read_text(encoding="utf-8"), filename=str(stack_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("infra_seedwork"):
                continue
            mod = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(mod, alias.name), (
                    f"{stack_file.relative_to(AWS_ROOT)} imports missing symbol "
                    f"'{alias.name}' from '{node.module}'"
                )
