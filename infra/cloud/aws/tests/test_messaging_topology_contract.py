"""Contract and unit tests for topology-driven SQS IAM ARN resolution."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Callable
from pathlib import Path

import pulumi
import pytest
from infra_seedwork.messaging import (
    TopologyConfig,
    merge_messaging_queue_arns,
    provision_from_topology,
    resolve_messaging_queue_arns,
    select_messaging_queue_arns,
    sqs_arns_from_queue_env_vars,
    sqs_url_to_arn,
)
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


def test_compute_and_messaging_stacks_enforce_ssot_queue_arns_contract() -> None:
    """Enforce zero hardcoded per-queue *_arn require_output calls across all compute stacks."""
    messaging_stacks = [
        AWS_ROOT / "apps" / "ucp" / "messaging" / "__main__.py",
        AWS_ROOT / "apps" / "identity" / "messaging" / "__main__.py",
        AWS_ROOT / "apps" / "notification" / "messaging" / "__main__.py",
        AWS_ROOT / "apps" / "edi" / "messaging" / "__main__.py",
    ]
    for stack_file in messaging_stacks:
        source = stack_file.read_text(encoding="utf-8")
        assert 'pulumi.export("queue_arns", result.queue_arns)' in source, (
            f"{stack_file} must export structured 'queue_arns' from TopologyOutput"
        )

    compute_stacks = [
        AWS_ROOT / "apps" / "ucp" / "workers" / "__main__.py",
        AWS_ROOT / "apps" / "edi" / "workers" / "__main__.py",
        AWS_ROOT / "apps" / "edi" / "as2" / "__main__.py",
        AWS_ROOT / "apps" / "api" / "__main__.py",
    ]
    for stack_file in compute_stacks:
        source = stack_file.read_text(encoding="utf-8")
        assert "sqs:GetQueueUrl" not in source, (
            f"{stack_file} must not grant sqs:GetQueueUrl (violates static QueueUrl injection)"
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
                assert not (output_key.endswith("_queue_arn") or output_key.startswith("sqs_")), (
                    f"{stack_file} calls require_output({output_key!r}); "
                    "use resolve_messaging_queue_arns / merge_messaging_queue_arns instead"
                )
