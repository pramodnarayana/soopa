import json

import pulumi_aws as aws
from seedwork.messaging import provision_fifo_queue_pair, subscribe_queue


def provision_messaging(prefix: str, tags: dict, platform_events_topic_arn: str):

    # Helper for FIFO Queue Pairs using seedwork
    def make_fifo_queue_pair(name: str):
        return provision_fifo_queue_pair(f"{prefix}{name}", tags)

    # Helper for Subscription using seedwork
    def subscribe(name: str, topic_arn: str, queue: aws.sqs.Queue, filter_policy: dict = None):
        return subscribe_queue(f"{prefix}{name}", topic_arn, queue, filter_policy)

    # Queues
    transform_q, _ = make_fifo_queue_pair("transform")
    compute_q, _ = make_fifo_queue_pair("compute")
    lifecycle_q, _ = make_fifo_queue_pair("lifecycle")
    deliver_q, _ = make_fifo_queue_pair("deliver")
    config_sync_q, _ = make_fifo_queue_pair("config-sync")
    data_plane_jobs_q, _ = make_fifo_queue_pair("data-plane-jobs")
    control_plane_jobs_q, _ = make_fifo_queue_pair("control-plane-jobs")
    priority_notifications_q, _ = make_fifo_queue_pair("priority-notifications")

    # Subscriptions

    subscribe(
        "config-sync-sub",
        platform_events_topic_arn,
        config_sync_q,
        json.dumps({"event_type": [{"prefix": "webhook."}, {"prefix": "edi."}]}),
    )

    subscribe(
        "transform-sub",
        platform_events_topic_arn,
        transform_q,
        json.dumps({"event_type": ["pipeline.transform_event"]}),
    )
    subscribe(
        "compute-sub",
        platform_events_topic_arn,
        compute_q,
        json.dumps({"event_type": ["pipeline.compute_transform_event"]}),
    )
    subscribe(
        "lifecycle-sub",
        platform_events_topic_arn,
        lifecycle_q,
        json.dumps({"event_type": ["pipeline.transform_completed", "pipeline.delivery_completed"]}),
    )
    subscribe(
        "deliver-sub",
        platform_events_topic_arn,
        deliver_q,
        json.dumps({"event_type": ["pipeline.deliver_event"]}),
    )
    subscribe(
        "notifications-sub",
        platform_events_topic_arn,
        priority_notifications_q,
        json.dumps({"event_type": [{"prefix": "notification."}]}),
    )

    return {
        "queues": {
            "transform": transform_q,
            "compute": compute_q,
            "lifecycle": lifecycle_q,
            "deliver": deliver_q,
            "config_sync": config_sync_q,
            "data_plane_jobs": data_plane_jobs_q,
            "control_plane_jobs": control_plane_jobs_q,
            "priority_notifications": priority_notifications_q,
        },
    }
