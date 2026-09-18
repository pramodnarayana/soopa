import json

import pulumi
import pulumi_aws as aws


def provision_fifo_queue_pair(
    name: str, tags: dict, max_receive_count: int = 5
) -> tuple[aws.sqs.Queue, aws.sqs.Queue]:
    """
    Provisions a FIFO SQS queue and its paired dead-letter queue.
    """
    dlq = aws.sqs.Queue(
        f"{name}-dlq",
        name=f"{name}-dlq.fifo",
        fifo_queue=True,
        content_based_deduplication=True,
        tags=tags,
    )

    queue = aws.sqs.Queue(
        name,
        name=f"{name}.fifo",
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


def subscribe_queue(
    subscription_name: str,
    topic: aws.sns.Topic,
    queue: aws.sqs.Queue,
    filter_policy: dict = None,
) -> aws.sns.TopicSubscription:
    """
    Subscribes an SQS queue to an SNS topic using enterprise-grade MessageAttributes routing.
    """
    aws.sqs.QueuePolicy(
        f"{subscription_name}-policy",
        queue_url=queue.url,
        policy=pulumi.Output.all(topic.arn, queue.arn).apply(
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
        topic=topic.arn,
        protocol="sqs",
        endpoint=queue.arn,
        raw_message_delivery=True,
        filter_policy=json.dumps(filter_policy) if filter_policy else None,
        filter_policy_scope="MessageAttributes" if filter_policy else None,
    )
