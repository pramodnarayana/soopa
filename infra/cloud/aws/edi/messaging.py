"""
EDI Messaging Infrastructure
=============================

Provisions all SQS queues (with DLQs), SNS topics, and SNS→SQS subscriptions
for the EDI bounded context.

Design decisions
----------------
- Every source queue has a paired DLQ with a maxReceiveCount of 5.
- All queues are FIFO with content-based deduplication to guarantee
  exactly-once delivery for pipeline events.
- SNS→SQS subscriptions use message-body filter policies so each worker
  receives only the event types it is responsible for.
- ``RawMessageDelivery=true`` on every subscription so consumers receive
  the raw JSON payload without an SNS envelope wrapper.

Queue topology (mirrors localstack-setup.sh exactly)
-----------------------------------------------------
edi-transform.fifo          ← TRANSFORM_EVENT, COMPUTE_TRANSFORM_EVENT
edi-lifecycle.fifo          ← TRANSFORM_COMPLETED, DELIVERY_COMPLETED
edi-deliver.fifo            ← DELIVER_EVENT
edi-config-sync-queue.fifo  ← all other provisioning events
edi-data-plane-jobs.fifo    ← scheduled background job triggers (data plane)
edi-control-plane-jobs.fifo ← scheduled background job triggers (control plane)
edi-priority-notifications.fifo ← notification.triggered
"""

import json
from dataclasses import dataclass

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class FifoQueuePair:
    """A source FIFO queue paired with its dead-letter queue."""

    queue: aws.sqs.Queue
    dlq: aws.sqs.Queue


def _make_fifo_queue_pair(
    logical_name: str,
    queue_name: str,
    dlq_name: str,
    max_receive_count: int | None = None,
) -> FifoQueuePair:
    config = pulumi.Config("edi-platform")
    mrc = (
        max_receive_count
        if max_receive_count is not None
        else config.require_int("dlq_max_receive_count")
    )
    """
    Provisions a FIFO SQS queue and its dead-letter queue as a pair.

    All queues use content-based deduplication so producers do not need
    to supply a deduplication ID on every message.
    """
    dlq = aws.sqs.Queue(
        f"{logical_name}-dlq",
        name=dlq_name,
        fifo_queue=True,
        content_based_deduplication=True,
        tags={"ManagedBy": "pulumi", "Component": "edi"},
    )

    redrive_policy = pulumi.Output.all(dlq.arn).apply(
        lambda args: json.dumps({"deadLetterTargetArn": args[0], "maxReceiveCount": mrc})
    )

    queue = aws.sqs.Queue(
        logical_name,
        name=queue_name,
        fifo_queue=True,
        content_based_deduplication=True,
        redrive_policy=redrive_policy,
        tags={"ManagedBy": "pulumi", "Component": "edi"},
    )

    return FifoQueuePair(queue=queue, dlq=dlq)


def _make_fifo_topic(logical_name: str, topic_name: str) -> aws.sns.Topic:
    """Provisions a FIFO SNS topic with content-based deduplication."""
    return aws.sns.Topic(
        logical_name,
        name=topic_name,
        fifo_topic=True,
        content_based_deduplication=True,
        tags={"ManagedBy": "pulumi", "Component": "edi"},
    )


def _subscribe_queue(
    logical_name: str,
    topic: aws.sns.Topic,
    queue_pair: FifoQueuePair,
    filter_policy: dict | None = None,
) -> aws.sns.TopicSubscription:
    """
    Subscribes a queue to a topic with optional message-body filter policy.

    RawMessageDelivery is always enabled so consumers receive the bare JSON
    payload, not an SNS-wrapped envelope.
    """
    attributes: dict[str, str] = {"RawMessageDelivery": "true"}
    if filter_policy:
        attributes["FilterPolicy"] = json.dumps(filter_policy)
        attributes["FilterPolicyScope"] = "MessageBody"

    # Grant the SNS topic permission to send messages to the SQS queue.
    aws.sqs.QueuePolicy(
        f"{logical_name}-policy",
        queue_url=queue_pair.queue.url,
        policy=pulumi.Output.all(topic.arn, queue_pair.queue.arn).apply(
            lambda args: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "sns.amazonaws.com"},
                            "Action": "sqs:SendMessage",
                            "Resource": args[1],
                            "Condition": {"ArnEquals": {"aws:SourceArn": args[0]}},
                        }
                    ],
                }
            )
        ),
    )

    return aws.sns.TopicSubscription(
        logical_name,
        topic=topic.arn,
        protocol="sqs",
        endpoint=queue_pair.queue.arn,
        subscription_role_arn=None,
        raw_message_delivery=True,
        filter_policy=json.dumps(filter_policy) if filter_policy else None,
        filter_policy_scope="MessageBody" if filter_policy else None,
    )


class EdiMessagingStack:
    """
    Composes all messaging infrastructure for the EDI bounded context.

    Instantiate once from ``__main__.py``. All queue pairs and topic
    references are available as attributes for export.
    """

    def __init__(self) -> None:
        # ── SNS Topics ────────────────────────────────────────────────────────
        self.edi_events_topic = _make_fifo_topic("edi-events-topic", "edi-events-topic.fifo")
        self.ucp_events_topic = _make_fifo_topic("ucp-events-topic", "ucp-events-topic.fifo")
        self.identity_events_topic = _make_fifo_topic(
            "identity-events-topic", "identity-events-topic.fifo"
        )

        # ── SQS Queue Pairs ───────────────────────────────────────────────────
        self.edi_transform = _make_fifo_queue_pair(
            "edi-transform",
            queue_name="edi-transform.fifo",
            dlq_name="edi-transform-dlq.fifo",
        )
        self.edi_lifecycle = _make_fifo_queue_pair(
            "edi-lifecycle",
            queue_name="edi-lifecycle.fifo",
            dlq_name="edi-lifecycle-dlq.fifo",
        )
        self.edi_deliver = _make_fifo_queue_pair(
            "edi-deliver",
            queue_name="edi-deliver.fifo",
            dlq_name="edi-deliver-dlq.fifo",
        )
        self.edi_config_sync = _make_fifo_queue_pair(
            "edi-config-sync",
            queue_name="edi-config-sync-queue.fifo",
            dlq_name="edi-config-sync-queue-dlq.fifo",
        )
        self.edi_data_plane_jobs = _make_fifo_queue_pair(
            "edi-data-plane-jobs",
            queue_name="edi-data-plane-jobs.fifo",
            dlq_name="edi-data-plane-jobs-dlq.fifo",
        )
        self.edi_control_plane_jobs = _make_fifo_queue_pair(
            "edi-control-plane-jobs",
            queue_name="edi-control-plane-jobs.fifo",
            dlq_name="edi-control-plane-jobs-dlq.fifo",
        )
        self.edi_priority_notifications = _make_fifo_queue_pair(
            "edi-priority-notifications",
            queue_name="edi-priority-notifications.fifo",
            dlq_name="edi-priority-notifications-dlq.fifo",
        )

        # UCP and Identity queues (consumed by their respective bounded contexts)
        self.ucp_events = _make_fifo_queue_pair(
            "ucp-events",
            queue_name="ucp-events.fifo",
            dlq_name="ucp-events-dlq.fifo",
        )
        self.ucp_jobs = _make_fifo_queue_pair(
            "ucp-jobs",
            queue_name="ucp-jobs.fifo",
            dlq_name="ucp-jobs-dlq.fifo",
        )
        self.identity_events = _make_fifo_queue_pair(
            "identity-events",
            queue_name="identity-events.fifo",
            dlq_name="identity-events-dlq.fifo",
        )
        self.email_delivery = _make_fifo_queue_pair(
            "email-delivery",
            queue_name="email-delivery.fifo",
            dlq_name="email-delivery-dlq.fifo",
        )

        # ── SNS→SQS Subscriptions ─────────────────────────────────────────────
        # UCP events → ucp-events queue
        _subscribe_queue(
            "ucp-events-subscription",
            topic=self.ucp_events_topic,
            queue_pair=self.ucp_events,
        )

        # Identity events → identity-events queue
        _subscribe_queue(
            "identity-events-subscription",
            topic=self.identity_events_topic,
            queue_pair=self.identity_events,
        )

        # EDI events → transform queue (transform events only)
        _subscribe_queue(
            "edi-transform-subscription",
            topic=self.edi_events_topic,
            queue_pair=self.edi_transform,
            filter_policy={"eventType": ["TRANSFORM_EVENT", "COMPUTE_TRANSFORM_EVENT"]},
        )

        # EDI events → lifecycle queue (lifecycle completion events only)
        _subscribe_queue(
            "edi-lifecycle-subscription",
            topic=self.edi_events_topic,
            queue_pair=self.edi_lifecycle,
            filter_policy={"eventType": ["TRANSFORM_COMPLETED", "DELIVERY_COMPLETED"]},
        )

        # EDI events → deliver queue (deliver events only)
        _subscribe_queue(
            "edi-deliver-subscription",
            topic=self.edi_events_topic,
            queue_pair=self.edi_deliver,
            filter_policy={"eventType": ["DELIVER_EVENT"]},
        )

        # EDI events → config-sync queue (all provisioning events — everything
        # except data-plane pipeline and notification events)
        _subscribe_queue(
            "edi-config-sync-subscription",
            topic=self.edi_events_topic,
            queue_pair=self.edi_config_sync,
            filter_policy={
                "eventType": [
                    {
                        "anything-but": [
                            "TRANSFORM_EVENT",
                            "COMPUTE_TRANSFORM_EVENT",
                            "TRANSFORM_COMPLETED",
                            "DELIVERY_COMPLETED",
                            "DELIVER_EVENT",
                            "notification.triggered",
                        ]
                    }
                ]
            },
        )
