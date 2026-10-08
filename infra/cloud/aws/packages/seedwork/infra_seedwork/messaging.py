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
from dataclasses import dataclass, field
from typing import TypedDict

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
        tags=tags,
    )

    queue = aws.sqs.Queue(
        logical_name,
        name=f"{logical_name}.fifo",
        fifo_queue=True,
        content_based_deduplication=True,
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
    """
    dlq = aws.sqs.Queue(
        f"{name}-dlq",
        name=f"{name}-dlq",
        fifo_queue=False,
        tags=tags,
    )

    queue = aws.sqs.Queue(
        name,
        name=name,
        fifo_queue=False,
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

    ``queue_env_vars`` is the only field compute stacks should consume.
    It is a Pulumi Output resolving to ``{ "ENV_VAR_NAME": "https://sqs-url..." }``
    for every queue/topic that declares an ``env_var`` in topology.json.

    Compute stacks pass this into ``infra_seedwork.env.queue_env_vars_to_ecs_format``
    inside an ``.apply()`` callback — zero manual per-queue mapping ever required.
    """

    # Pulumi Output[dict[str, str]] — env_var → resolved URL/ARN.
    # Exported by messaging stacks, consumed by compute stacks.
    queue_env_vars: pulumi.Output[dict[str, str]]

    # Raw queue objects keyed by topology queue name, for stacks that need
    # to wire subscriptions or grant extra IAM permissions.
    queues: dict[str, aws.sqs.Queue] = field(default_factory=dict)

    # Raw topic objects keyed by topology topic name.
    topics: dict[str, aws.sns.Topic] = field(default_factory=dict)


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
        if queue_conf.get("fifo"):
            q, _ = provision_fifo_queue_pair(prefixed_name, tags)
        else:
            q, _ = provision_standard_queue_pair(prefixed_name, tags)
        queues[name] = q

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

    # Resolve the dict of Outputs into a single Output[dict[str, str]].
    # pulumi.Output.all(**kwargs) resolves to dict[str, str] directly —
    # no .apply() passthrough needed.
    resolved: pulumi.Output[dict[str, str]] = (
        pulumi.Output.all(**env_var_outputs) if env_var_outputs else pulumi.Output.from_input({})
    )

    return TopologyOutput(queue_env_vars=resolved, queues=queues, topics=topics)
