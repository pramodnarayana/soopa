"""
Application Layer (Layer 3) - UCP Bounded Context: Messaging (Retired)
======================================================================
AWS SQS/SNS resources for UCP have been retired in favor of PostgreSQL Pub/Sub
(`pubsub.platform_queue_messages` & `pubsub.platform_topic_subscriptions`).

Retaining this zero-resource stack ensures the next `pulumi up` cleanly destroys
any legacy SQS queues, DLQs, and SNS subscriptions in AWS state without orphaning them.
"""

import pulumi
from infra_seedwork.messaging import build_database_pubsub_env_vars
from infra_seedwork.topology import load_topology

topology = load_topology()
queue_env_vars = build_database_pubsub_env_vars(
    topology=topology,
    queue_filter={"ucp-events", "ucp-jobs"},
    topic_filter=set(),
)

pulumi.export("queue_env_vars", queue_env_vars)
pulumi.export("queue_arns", [])
