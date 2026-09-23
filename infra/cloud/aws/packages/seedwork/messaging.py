import json

import pulumi
import pulumi_aws as aws


def provision_fifo_queue_pair(
    logical_name: str, tags: dict, max_receive_count: int = 5
) -> tuple[aws.sqs.Queue, aws.sqs.Queue]:
    """
    Provisions a FIFO SQS queue and its paired dead-letter queue.
    Accepts purely logical names (e.g. 'edi-config-sync-queue') and enforces
    Enterprise Fail-Fast architectural boundaries by rejecting AWS-specific suffixes.
    """
    if logical_name.endswith(".fifo"):
        raise ValueError(
            f"Queue logical name '{logical_name}' must not include the '.fifo' suffix. Pass the base logical name only."
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
    name: str, tags: dict, max_receive_count: int = 5
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
    filter_policy: dict = None,
) -> aws.sns.TopicSubscription:
    """
    Subscribes an SQS queue to an SNS topic using enterprise-grade MessageAttributes routing.
    """
    aws.sqs.QueuePolicy(
        f"{subscription_name}-policy",
        queue_url=queue.url,
        policy=pulumi.Output.all(topic_arn, queue.arn).apply(
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
        subscription_name,
        topic=topic_arn,
        protocol="sqs",
        endpoint=queue.arn,
        raw_message_delivery=True,
        filter_policy=json.dumps(filter_policy) if filter_policy else None,
        filter_policy_scope="MessageAttributes" if filter_policy else None,
    )
