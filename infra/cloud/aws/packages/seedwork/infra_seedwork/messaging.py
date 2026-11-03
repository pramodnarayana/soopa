"""
infra_seedwork.messaging
========================
Enterprise-grade SQS/SNS provisioning helpers.

The central primitive is ``provision_from_topology``, which reads the parsed
topology dict and returns structured outputs that drive zero-touch environment
variable injection in every compute stack. Compute stacks NEVER manually map
individual queue URLs to environment variable names — they always consume the
structured ``TopologyOutput.queue_env_vars`` from here.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypedDict
from urllib.parse import urlparse

import pulumi
import pulumi_aws as aws

# ---------------------------------------------------------------------------
# Typed topology schema
# ---------------------------------------------------------------------------


class QueueConfig(TypedDict, total=False):
    name: str
    fifo: bool
    dlq: bool
    env_var: str
    dlq_env_var: str
    max_receive_count: int


class TopicConfig(TypedDict, total=False):
    name: str
    fifo: bool
    env_var: str


class SubscriptionConfig(TypedDict, total=False):
    topic: str
    queue: str
    filterPolicy: dict[str, object]


class TopologyConfig(TypedDict, total=False):
    topics: list[TopicConfig]
    queues: list[QueueConfig]
    subscriptions: list[SubscriptionConfig]
    buckets: list[dict[str, str]]
    secrets: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Low-level queue/topic primitives
# ---------------------------------------------------------------------------


def provision_fifo_queue_pair(
    logical_name: str, tags: dict[str, str], max_receive_count: int = 5
) -> tuple[aws.sqs.Queue, aws.sqs.Queue]:
    """
    Provisions a FIFO SQS queue and its paired dead-letter queue.
    Accepts purely logical names (e.g. 'edi-config-sync-queue') and enforces
    Enterprise Fail-Fast architectural boundaries by rejecting AWS-specific suffixes.
    Enforces SQS long polling (20 seconds) to minimize empty poll API charges.
    """
    if logical_name.endswith(".fifo"):
        raise ValueError(
            f"Queue logical name '{logical_name}' must not include the '.fifo' suffix. "
            "Pass the base logical name only."
        )

    dlq = aws.sqs.Queue(
        f"{logical_name}-dlq",
        name=f"{logical_name}-dlq.fifo",
        fifo_queue=True,
        content_based_deduplication=True,
        receive_wait_time_seconds=20,
        tags=tags,
    )

    queue = aws.sqs.Queue(
        logical_name,
        name=f"{logical_name}.fifo",
        fifo_queue=True,
        content_based_deduplication=True,
        receive_wait_time_seconds=20,
        redrive_policy=pulumi.Output.all(dlq.arn).apply(
            lambda args: json.dumps(
                {"deadLetterTargetArn": args[0], "maxReceiveCount": max_receive_count}
            )
        ),
        tags=tags,
    )
    return queue, dlq


def provision_standard_queue_pair(
    name: str, tags: dict[str, str], max_receive_count: int = 5
) -> tuple[aws.sqs.Queue, aws.sqs.Queue]:
    """
    Provisions a Standard SQS queue and its paired dead-letter queue.
    Enforces SQS long polling (20 seconds) to minimize empty poll API charges.
    """
    dlq = aws.sqs.Queue(
        f"{name}-dlq",
        name=f"{name}-dlq",
        fifo_queue=False,
        receive_wait_time_seconds=20,
        tags=tags,
    )

    queue = aws.sqs.Queue(
        name,
        name=name,
        fifo_queue=False,
        receive_wait_time_seconds=20,
        redrive_policy=pulumi.Output.all(dlq.arn).apply(
            lambda args: json.dumps(
                {"deadLetterTargetArn": args[0], "maxReceiveCount": max_receive_count}
            )
        ),
        tags=tags,
    )
    return queue, dlq


def subscribe_queue(
    subscription_name: str,
    topic_arn: pulumi.Input[str],
    queue: aws.sqs.Queue,
    filter_policy: dict[str, object] | None = None,
) -> aws.sns.TopicSubscription:
    """
    Subscribes an SQS queue to an SNS topic using enterprise-grade MessageAttributes routing.

    Args:
        subscription_name: Logical name for the subscription resource.
        topic_arn: ARN of the SNS topic to subscribe to.
        queue: The SQS queue to register as the subscriber endpoint.
        filter_policy: Optional plain Python dict for SNS MessageAttribute filtering.
                       Must NOT be pre-serialized with json.dumps() — this function
                       handles serialization internally. Raises TypeError if violated.
    """
    if filter_policy is not None and not isinstance(filter_policy, dict):
        raise TypeError(
            f"subscribe_queue() 'filter_policy' must be a plain dict, "
            f"got {type(filter_policy).__name__!r}. "
            "Do not pre-serialize with json.dumps() — this function handles serialization internally."
        )

    return aws.sns.TopicSubscription(
        subscription_name,
        topic=topic_arn,
        protocol="sqs",
        endpoint=queue.arn,
        raw_message_delivery=True,
        filter_policy=json.dumps(filter_policy) if filter_policy else None,
        filter_policy_scope="MessageAttributes" if filter_policy else None,
    )


# ---------------------------------------------------------------------------
# Enterprise topology-driven provisioning
# ---------------------------------------------------------------------------


@dataclass
class TopologyOutput:
    """
    Structured result of provisioning queues/topics for a bounded context.

    ``queue_env_vars`` and ``queue_arns`` are the canonical SSOT exports that
    compute stacks consume:
    - ``queue_env_vars`` resolves to ``{ "ENV_VAR_NAME": "https://sqs-url..." }``
      for zero-touch container environment variable injection.
    - ``queue_arns`` resolves to a sorted list of SQS Queue ARNs (including
      consumed DLQs) for zero-touch least-privilege IAM task role policies.
    """

    # Pulumi Output[dict[str, str]] — env_var → resolved URL/ARN.
    # Exported by messaging stacks, consumed by compute stacks.
    queue_env_vars: pulumi.Output[dict[str, str]]

    # Pulumi Output[list[str]] — sorted list of provisioned SQS queue + consumed DLQ ARNs.
    # Exported by messaging stacks, consumed via resolve_messaging_queue_arns().
    queue_arns: pulumi.Output[list[str]]

    # Raw queue objects keyed by topology queue name, for stacks that need
    # to wire subscriptions or grant extra IAM permissions.
    queues: dict[str, aws.sqs.Queue] = field(default_factory=dict)

    # Raw dlq queue objects keyed by topology queue name.
    dlqs: dict[str, aws.sqs.Queue] = field(default_factory=dict)

    # Raw topic objects keyed by topology topic name.
    topics: dict[str, aws.sns.Topic] = field(default_factory=dict)


def _aws_partition_for_region(region: str) -> str:
    """Resolve the IAM ARN partition for a given AWS region identifier."""
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    if region.startswith("cn-"):
        return "aws-cn"
    return "aws"


def sqs_url_to_arn(queue_url: str) -> str:
    """
    Deterministically convert a canonical AWS SQS Queue URL into an IAM Queue ARN.

    Accepts standard and FIFO AWS SQS URLs of the form:
    ``https://sqs.<region>.amazonaws.com/<account_id>/<queue_name>``

    Raises:
        ValueError: If ``queue_url`` is not a valid AWS SQS queue URL.
    """
    if not queue_url:
        raise ValueError(f"Invalid AWS SQS queue URL: {queue_url!r}")

    parsed = urlparse(queue_url)
    hostname = parsed.hostname or ""
    host_parts = hostname.split(".")
    if (
        parsed.scheme not in ("https", "http")
        or len(host_parts) < 4
        or host_parts[0] != "sqs"
        or "amazonaws" not in host_parts
    ):
        raise ValueError(f"Invalid AWS SQS queue URL: {queue_url!r}")

    region = host_parts[1]
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if len(path_segments) != 2 or not region or not path_segments[0].isdigit():
        raise ValueError(f"Invalid AWS SQS queue URL: {queue_url!r}")

    account_id, queue_name = path_segments[0], path_segments[1]
    partition = _aws_partition_for_region(region)
    return f"arn:{partition}:sqs:{region}:{account_id}:{queue_name}"


def sqs_arns_from_queue_env_vars(queue_env_vars: Mapping[str, object]) -> list[str]:
    """
    Derive sorted, deduplicated SQS Queue ARNs from a ``queue_env_vars`` export map.

    Ignores SNS topic ARNs (``arn:*:sns:...``) that may share the ``queue_env_vars`` map.
    """
    arns: set[str] = set()
    for raw_val in queue_env_vars.values():
        if not isinstance(raw_val, str) or not raw_val:
            continue
        if raw_val.startswith("arn:"):
            if ":sqs:" in raw_val:
                arns.add(raw_val)
            continue
        arns.add(sqs_url_to_arn(raw_val))
    return sorted(arns)


def select_messaging_queue_arns(
    exported_queue_arns: Sequence[object] | None,
    exported_queue_env_vars: Mapping[str, object] | None,
) -> list[str]:
    """
    Select canonical SQS Queue ARNs for a messaging stack reference.

    Prefers the structured ``queue_arns`` export in steady state, and falls back
    to deriving ARNs from ``queue_env_vars`` during speculative PR previews before
    ``queue_arns`` has been rolled out to backend state.
    """
    if exported_queue_arns is not None:
        return sorted({str(arn) for arn in exported_queue_arns if isinstance(arn, str) and arn})
    if exported_queue_env_vars is not None:
        return sqs_arns_from_queue_env_vars(exported_queue_env_vars)
    return []


def resolve_messaging_queue_arns(stack_ref: pulumi.StackReference) -> pulumi.Output[list[str]]:
    """
    Resolve SQS Queue ARNs from a bounded-context messaging ``StackReference``.

    Safe for both steady-state deployments and speculative PR previews without
    ever requiring per-queue ``require_output(...)`` coupling in compute stacks.
    """

    def _select(args: list[object]) -> list[str]:
        raw_arns = (
            args[0] if isinstance(args[0], Sequence) and not isinstance(args[0], str) else None
        )
        raw_env_vars = args[1] if isinstance(args[1], Mapping) else None
        return select_messaging_queue_arns(raw_arns, raw_env_vars)

    return pulumi.Output.all(
        stack_ref.get_output("queue_arns"),
        stack_ref.get_output("queue_env_vars"),
    ).apply(_select)


def merge_messaging_queue_arns(*stack_refs: pulumi.StackReference) -> pulumi.Output[list[str]]:
    """Resolve and merge deduplicated SQS Queue ARNs across multiple messaging stacks."""
    if not stack_refs:
        return pulumi.Output.from_input([])

    resolved_per_stack = [resolve_messaging_queue_arns(ref) for ref in stack_refs]
    return pulumi.Output.all(*resolved_per_stack).apply(
        lambda groups: sorted({arn for group in groups for arn in group})
    )


def provision_from_topology(  # noqa: C901 - Infrastructure assembler natively requires high branching logic to support multiple topological permutations
    topology: TopologyConfig,
    prefix: str,
    tags: dict[str, str],
    *,
    queue_filter: set[str] | None = None,
    topic_filter: set[str] | None = None,
    external_topic_arns: dict[str, pulumi.Input[str]] | None = None,
) -> TopologyOutput:
    """
    Provisions SQS queues and SNS topics declared in topology.json for a
    single bounded context, then wires SNS subscriptions.

    This is the enterprise SSOT driver. Calling code passes ``queue_filter``
    and ``topic_filter`` to select only the resources belonging to its bounded
    context. The function returns a ``TopologyOutput`` whose ``queue_env_vars``
    field is the *single export* that every compute stack consumes.

    Raises:
        ValueError: If topology.json declares two queues/topics with the same
                    ``env_var`` name within this bounded context. Fail fast —
                    never silently overwrite.

    Args:
        topology:            Parsed topology dict (use ``load_topology()``).
        prefix:              Physical AWS name prefix (e.g. ``"staging-edi-"``).
        tags:                AWS resource tags.
        queue_filter:        Set of topology queue names to provision. If None,
                             provisions ALL queues in topology.
        topic_filter:        Set of topology topic names to provision. If None,
                             provisions ALL topics in topology.
        external_topic_arns: Map of topic name → ARN for topics owned by another
                             stack that are referenced in subscriptions (e.g.
                             ``"platform-events-topic"`` owned by the platform stack).

    Returns:
        TopologyOutput with provisioned queues/topics and a structured env-var map.
    """
    external_topic_arns = external_topic_arns or {}
    queues: dict[str, aws.sqs.Queue] = {}
    dlqs: dict[str, aws.sqs.Queue] = {}
    topics: dict[str, aws.sns.Topic] = {}

    # ── Provision topics ─────────────────────────────────────────────────────
    for topic_conf in topology.get("topics", []):
        name = topic_conf["name"]
        if topic_filter is not None and name not in topic_filter:
            continue
        is_fifo = topic_conf.get("fifo", False)
        physical_name = f"{prefix}{name}.fifo" if is_fifo else f"{prefix}{name}"
        topics[name] = aws.sns.Topic(
            f"{prefix}{name}",
            name=physical_name,
            fifo_topic=is_fifo,
            content_based_deduplication=is_fifo or None,
            tags=tags,
        )

    # ── Provision queues ─────────────────────────────────────────────────────
    for queue_conf in topology.get("queues", []):
        name = queue_conf["name"]
        if queue_filter is not None and name not in queue_filter:
            continue
        prefixed_name = f"{prefix}{name}"
        max_receive_count = queue_conf.get("max_receive_count", 5)
        if queue_conf.get("fifo"):
            q, d = provision_fifo_queue_pair(
                prefixed_name, tags, max_receive_count=max_receive_count
            )
        else:
            q, d = provision_standard_queue_pair(
                prefixed_name, tags, max_receive_count=max_receive_count
            )
        queues[name] = q
        dlqs[name] = d

    # ── Wire SNS subscriptions ───────────────────────────────────────────────
    available_topics: dict[str, pulumi.Input[str]] = {
        **external_topic_arns,
        **{k: v.arn for k, v in topics.items()},
    }
    # Keep track of topic ARNs subscribed to each queue for policy generation
    queue_subscriptions: dict[str, list[pulumi.Input[str]]] = {q_name: [] for q_name in queues}

    for sub in topology.get("subscriptions", []):
        topic_name = sub["topic"]
        queue_name = sub["queue"]
        topic_arn = available_topics.get(topic_name)
        if topic_arn and queue_name in queues:
            # Deterministic naming: Hash the filter policy so that array reordering doesn't destroy/recreate resources.
            filter_policy = sub.get("filterPolicy", {})
            policy_hash = hashlib.md5(  # noqa: S324 - md5 used only for deterministic resource naming
                json.dumps(filter_policy, sort_keys=True).encode()
            ).hexdigest()[:6]

            subscribe_queue(
                f"{prefix}{queue_name}-{topic_name}-sub-{policy_hash}",
                topic_arn,
                queues[queue_name],
                filter_policy,
            )
            queue_subscriptions[queue_name].append(topic_arn)

    # ── Create aggregated Queue Policies ──────────────────────────────────────
    for queue_name, topic_arns in queue_subscriptions.items():
        if not topic_arns:
            continue

        aws.sqs.QueuePolicy(
            f"{prefix}{queue_name}-policy",
            queue_url=queues[queue_name].url,
            policy=pulumi.Output.all(queues[queue_name].arn, *topic_arns).apply(
                lambda args: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "sns.amazonaws.com"},
                                "Action": "sqs:SendMessage",
                                "Resource": args[0],
                                "Condition": {"ArnEquals": {"aws:SourceArn": list(args[1:])}},
                            }
                        ],
                    }
                )
            ),
        )

    # ── Build the env-var output map ─────────────────────────────────────────
    # Collect every (env_var, Pulumi.Output[url/arn]) pair declared in topology.
    # Fail fast on duplicate env_var keys — never silently overwrite.
    env_var_outputs: dict[str, pulumi.Output[str]] = {}
    already_assigned: dict[str, str] = {}

    for queue_conf in topology.get("queues", []):
        env_var = queue_conf.get("env_var")
        name = queue_conf["name"]
        if env_var and name in queues:
            if env_var in env_var_outputs:
                raise ValueError(
                    f"Duplicate env_var '{env_var}' declared in topology.json for "
                    f"queue '{name}'. Each queue must have a unique env_var name. "
                    f"Already assigned to queue '{already_assigned[env_var]}'."
                )
            env_var_outputs[env_var] = queues[name].url
            already_assigned[env_var] = name

        dlq_env_var = queue_conf.get("dlq_env_var")
        if dlq_env_var and name in dlqs:
            if dlq_env_var in env_var_outputs:
                raise ValueError(
                    f"Duplicate env_var '{dlq_env_var}' declared in topology.json for "
                    f"queue dlq '{name}'. Already assigned to '{already_assigned[dlq_env_var]}'."
                )
            env_var_outputs[dlq_env_var] = dlqs[name].url
            already_assigned[dlq_env_var] = f"{name}-dlq"

    for topic_conf in topology.get("topics", []):
        env_var = topic_conf.get("env_var")
        name = topic_conf["name"]
        if env_var:
            if name in topics:
                if env_var in env_var_outputs:
                    raise ValueError(
                        f"Duplicate env_var '{env_var}' declared in topology.json for "
                        f"topic '{name}'. Already assigned to '{already_assigned[env_var]}'."
                    )
                env_var_outputs[env_var] = topics[name].arn
                already_assigned[env_var] = name
            elif name in external_topic_arns:
                if env_var in env_var_outputs:
                    raise ValueError(
                        f"Duplicate env_var '{env_var}' declared in topology.json for "
                        f"external topic '{name}'. Already assigned to '{already_assigned[env_var]}'."
                    )
                env_var_outputs[env_var] = pulumi.Output.from_input(external_topic_arns[name])
                already_assigned[env_var] = name

    # Collect every provisioned queue ARN + any consumed DLQ ARN (where dlq_env_var is set)
    # for zero-touch least-privilege IAM task role permissions in compute stacks.
    queue_arn_outputs: list[pulumi.Output[str]] = []
    for queue_conf in topology.get("queues", []):
        name = queue_conf["name"]
        if name in queues:
            queue_arn_outputs.append(queues[name].arn)
            if queue_conf.get("dlq_env_var") and name in dlqs:
                queue_arn_outputs.append(dlqs[name].arn)

    resolved_queue_arns: pulumi.Output[list[str]] = (
        pulumi.Output.all(*queue_arn_outputs).apply(lambda arns: sorted(set(arns)))
        if queue_arn_outputs
        else pulumi.Output.from_input([])
    )

    # Resolve the dict of Outputs into a single Output[dict[str, str]].
    # pulumi.Output.all(**kwargs) resolves to dict[str, str] directly —
    # no .apply() passthrough needed.
    resolved: pulumi.Output[dict[str, str]] = (
        pulumi.Output.all(**env_var_outputs) if env_var_outputs else pulumi.Output.from_input({})
    )

    return TopologyOutput(
        queue_env_vars=resolved,
        queue_arns=resolved_queue_arns,
        queues=queues,
        topics=topics,
        dlqs=dlqs,
    )
