import json
import os

import pulumi_aws as aws
from seedwork.messaging import (
    provision_fifo_queue_pair,
    provision_standard_queue_pair,
    subscribe_queue,
)


def provision_messaging(prefix: str, tags: dict, external_topics: dict = None):
    queues = {}
    topics = {}

    topology_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../../topology.json")
    )
    with open(topology_path) as f:
        topology = json.load(f)

    # ── Topics ──
    for topic in topology.get("topics", []):
        # We only want to provision EDI-owned topics in this stack.
        # Platform topics (like platform-events-topic) are provisioned by the platform stack.
        if topic["name"].startswith("edi-"):
            topics[topic["name"]] = aws.sns.Topic(
                f"{prefix}{topic['name']}",
                name=f"{prefix}{topic['name']}",
                fifo_topic=topic.get("fifo", False),
                content_based_deduplication=topic.get("fifo", False) or None,
                tags=tags,
            )

    # ── Queues ──
    for queue_conf in topology.get("queues", []):
        # For EDI context, we only provision queues starting with "edi-"
        name = queue_conf["name"]
        if not name.startswith("edi-") and not name.startswith("email-"):
            # skip identity and ucp queues, they belong elsewhere (or we provision them all here for simplicity)
            # Actually, to make it simple and fully mirror localstack, we will provision ALL of them here
            # because we don't have separate Pulumi stacks for Identity/UCP right now.
            pass

        prefixed_name = f"{prefix}{name}"
        if queue_conf.get("fifo"):
            q, _ = provision_fifo_queue_pair(prefixed_name, tags)
        else:
            q, _ = provision_standard_queue_pair(prefixed_name, tags)

        queues[name] = q

    # Build a lookup dictionary of available topics
    available_topics = external_topics.copy() if external_topics else {}
    for topic_name, topic in topics.items():
        available_topics[topic_name] = topic.arn

    # ── Subscriptions ──
    for sub in topology.get("subscriptions", []):
        topic_name = sub["topic"]
        queue_name = sub["queue"]

        topic_arn = available_topics.get(topic_name)
        if not topic_arn:
            continue

        # Map back from the exact name in topology.json to the provisioned queue
        if queue_name in queues:
            subscribe_queue(
                f"{prefix}{queue_name}-sub",
                topic_arn,
                queues[queue_name],
                sub.get("filterPolicy"),
            )

    return {
        "queues": queues,
        "topics": topics,
    }
