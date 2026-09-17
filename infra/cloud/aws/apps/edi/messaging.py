import pulumi_aws as aws
from seedwork.messaging import provision_fifo_queue_pair, subscribe_queue


def provision_messaging(prefix: str, tags: dict):
    # Topics
    edi_events_topic = aws.sns.Topic(
        f"{prefix}events",
        name=f"{prefix}events.fifo",
        fifo_topic=True,
        content_based_deduplication=True,
        tags=tags,
    )

    # Helper for FIFO Queue Pairs using seedwork
    def make_fifo_queue_pair(name: str):
        return provision_fifo_queue_pair(f"{prefix}{name}", tags)

    # Helper for Subscription using seedwork
    def subscribe(
        name: str, topic: aws.sns.Topic, queue: aws.sqs.Queue, filter_policy: dict = None
    ):
        return subscribe_queue(f"{prefix}{name}", topic, queue, filter_policy)

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
    # Note: UCP events subscription to edi_config_sync_q requires the UCP topic,
    # which we will reference via a StackReference in the future.

    subscribe(
        "transform-sub", edi_events_topic, transform_q, {"event_type": ["pipeline.transform_event"]}
    )
    subscribe(
        "compute-sub",
        edi_events_topic,
        compute_q,
        {"event_type": ["pipeline.compute_transform_event"]},
    )
    subscribe(
        "lifecycle-sub",
        edi_events_topic,
        lifecycle_q,
        {"event_type": ["pipeline.transform_completed", "pipeline.delivery_completed"]},
    )
    subscribe(
        "deliver-sub", edi_events_topic, deliver_q, {"event_type": ["pipeline.deliver_event"]}
    )
    subscribe(
        "notifications-sub",
        edi_events_topic,
        priority_notifications_q,
        {"event_type": ["notification.triggered"]},
    )
    subscribe(
        "config-sync-sub",
        edi_events_topic,
        config_sync_q,
        {
            "event_type": [
                {
                    "anything-but": [
                        "pipeline.transform_event",
                        "pipeline.compute_transform_event",
                        "pipeline.transform_completed",
                        "pipeline.delivery_completed",
                        "pipeline.deliver_event",
                        "notification.triggered",
                    ]
                }
            ]
        },
    )

    return {
        "edi_events_topic": edi_events_topic,
        "queues": {
            "transform": transform_q,
            "compute": compute_q,
            "lifecycle": lifecycle_q,
            "deliver": deliver_q,
            "config_sync": config_sync_q,
            "data_plane_jobs": data_plane_jobs_q,
            "control_plane_jobs": control_plane_jobs_q,
        },
    }
