"""
Application Layer (Layer 3) - EDI Bounded Context: Messaging (Retired)
======================================================================
AWS SQS/SNS resources for EDI have been retired in favor of PostgreSQL Pub/Sub
(`db://` direct shard outbox draining + `pubsub.platform_queue_messages` &
`pubsub.platform_topic_subscriptions`).

Retaining this zero-resource stack ensures the next `pulumi up` cleanly destroys
any legacy SQS queues, DLQs, and SNS subscriptions in AWS state without orphaning them.
"""

import pulumi
from infra_seedwork.messaging import build_database_pubsub_env_vars
from infra_seedwork.topology import load_topology

topology = load_topology()
edi_queues = {
    name for q in topology.get("queues", []) if (name := q.get("name")) and name.startswith("edi-")
}
edi_topics = {
    name for t in topology.get("topics", []) if (name := t.get("name")) and name.startswith("edi-")
}

queue_env_vars = build_database_pubsub_env_vars(
    topology=topology,
    queue_filter=edi_queues,
    topic_filter=edi_topics,
)

pulumi.export("queue_env_vars", queue_env_vars)
pulumi.export("queue_arns", [])
