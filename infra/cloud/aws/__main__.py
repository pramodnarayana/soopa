"""
EDI Platform — AWS Infrastructure Entry Point
==============================================

Pulumi program for the EDI bounded context on AWS.
Provisions all SQS queues (with DLQs), SNS topics, SNS→SQS subscriptions,
S3 buckets, and the full ECS/ECR compute layer.

All resource outputs are exported so they can be injected into application
containers as environment variables at deploy time — never discovered
dynamically at runtime.

Directory
---------
infra/cloud/aws/           ← this Pulumi project root
    edi_infra/messaging.py ← SQS queues, SNS topics, subscriptions
    edi_infra/storage.py   ← S3 buckets
    edi_infra/compute.py   ← ECR, VPC, ECS cluster, task definitions, ALB

Environment variable → Pulumi export mapping
--------------------------------------------
SQS_TRANSFORM_QUEUE_URL          ← sqs_transform_queue_url
SQS_LIFECYCLE_QUEUE_URL          ← sqs_lifecycle_queue_url
SQS_DELIVER_QUEUE_URL            ← sqs_deliver_queue_url
SQS_PROVISIONING_QUEUE_URL       ← sqs_config_sync_queue_url
SQS_DATA_PLANE_JOBS_QUEUE_URL    ← sqs_data_plane_jobs_queue_url
SQS_CONTROL_PLANE_JOBS_QUEUE_URL ← sqs_control_plane_jobs_queue_url
AWS_SNS_TOPIC_ARN                ← sns_edi_events_topic_arn
S3_BUCKET                        ← s3_edi_payloads_bucket
ECR_REPOSITORY_URL               ← ecr_repository_url
ECS_CLUSTER_NAME                 ← ecs_cluster_name
AS2_SERVER_ALB_DNS               ← as2_server_alb_dns
"""

import pulumi
from edi_infra.compute import EdiComputeStack
from edi_infra.messaging import EdiMessagingStack
from edi_infra.storage import EdiStorageStack

# ── Compose stacks ────────────────────────────────────────────────────────────

messaging = EdiMessagingStack()
storage = EdiStorageStack()
compute = EdiComputeStack(messaging=messaging, storage=storage)

# ── Export all outputs for injection into application containers ──────────────

# SQS Queue URLs (injected as SQS_*_QUEUE_URL env vars)
pulumi.export("sqs_transform_queue_url", messaging.edi_transform.queue.url)
pulumi.export("sqs_lifecycle_queue_url", messaging.edi_lifecycle.queue.url)
pulumi.export("sqs_deliver_queue_url", messaging.edi_deliver.queue.url)
pulumi.export("sqs_config_sync_queue_url", messaging.edi_config_sync.queue.url)
pulumi.export("sqs_data_plane_jobs_queue_url", messaging.edi_data_plane_jobs.queue.url)
pulumi.export("sqs_control_plane_jobs_queue_url", messaging.edi_control_plane_jobs.queue.url)
pulumi.export(
    "sqs_priority_notifications_queue_url", messaging.edi_priority_notifications.queue.url
)

# SNS Topic ARNs (injected as AWS_SNS_TOPIC_ARN env vars)
pulumi.export("sns_edi_events_topic_arn", messaging.edi_events_topic.arn)
pulumi.export("sns_ucp_events_topic_arn", messaging.ucp_events_topic.arn)
pulumi.export("sns_identity_events_topic_arn", messaging.identity_events_topic.arn)

# S3 (injected as S3_BUCKET env var)
pulumi.export("s3_edi_payloads_bucket", storage.edi_payloads.bucket)
pulumi.export("s3_edi_payloads_bucket_arn", storage.edi_payloads.arn)

# Compute — used by CI/CD to push images and trigger deployments
pulumi.export("ecr_repository_url", compute.ecr_repository_url)
pulumi.export("ecs_cluster_name", compute.cluster_name)
pulumi.export("as2_server_alb_dns", compute.alb_dns_name)
