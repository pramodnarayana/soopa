import pulumi
import pulumi_aws as aws


def provision_event_bus(prefix: str, tags: dict):
    platform_events_topic = aws.sns.Topic(
        f"{prefix}platform-events-topic",
        name=f"{prefix}platform-events-topic.fifo",
        fifo_topic=True,
        content_based_deduplication=True,
        tags=tags,
        opts=pulumi.ResourceOptions(retain_on_delete=True),
    )
    return platform_events_topic
