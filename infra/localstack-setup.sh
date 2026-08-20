#!/bin/bash
echo "Initializing LocalStack SQS queues and SNS topics..."

# 1. Create SNS Topics
awslocal sns create-topic --name ucp-tenant-events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name ucp-user-events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name edi-outbox-events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true

# 2. Create SQS Queues
awslocal sqs create-queue --queue-name ucp-identity-sync-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp-identity-sync.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name ucp-jobs-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp-jobs.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name ucp.events-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp.events.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-tenant-sync-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-tenant-sync.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-config-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-config.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-transform-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-transform.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-lifecycle-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-lifecycle.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-deliver-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-deliver.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-priority-notifications-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-priority-notifications.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

# 3. Get ARNs
TENANT_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:ucp-tenant-events.fifo --query 'Attributes.TopicArn' --output text)
USER_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:ucp-user-events.fifo --query 'Attributes.TopicArn' --output text)
EDI_OUTBOX_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:edi-outbox-events.fifo --query 'Attributes.TopicArn' --output text)

UCP_ID_SYNC_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp-identity-sync.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
UCP_EVENTS_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp.events.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

EDI_TRANSFORM_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-transform.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_LIFECYCLE_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-lifecycle.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_DELIVER_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-deliver.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_CONFIG_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-config.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)


# 4. Subscribe Queues to Topics
awslocal sns subscribe --topic-arn $TENANT_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_ID_SYNC_ARN
awslocal sns subscribe --topic-arn $USER_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_ID_SYNC_ARN

awslocal sns subscribe --topic-arn $TENANT_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_EVENTS_ARN
awslocal sns subscribe --topic-arn $USER_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_EVENTS_ARN

# Setup Data Plane SNS to SQS Subscriptions with Payload Filtering
FILTER_TRANSFORM='{"event_type": ["TRANSFORM_EVENT", "COMPUTE_TRANSFORM_EVENT"]}'
awslocal sns subscribe \
    --topic-arn $EDI_OUTBOX_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_TRANSFORM_ARN \
    --attributes FilterPolicy="$FILTER_TRANSFORM",FilterPolicyScope="MessageBody",RawMessageDelivery="true"

FILTER_LIFECYCLE='{"event_type": ["TRANSFORM_COMPLETED", "DELIVERY_COMPLETED"]}'
awslocal sns subscribe \
    --topic-arn $EDI_OUTBOX_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_LIFECYCLE_ARN \
    --attributes FilterPolicy="$FILTER_LIFECYCLE",FilterPolicyScope="MessageBody",RawMessageDelivery="true"

FILTER_DELIVER='{"event_type": ["DELIVER_EVENT"]}'
awslocal sns subscribe \
    --topic-arn $EDI_OUTBOX_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_DELIVER_ARN \
    --attributes FilterPolicy="$FILTER_DELIVER",FilterPolicyScope="MessageBody",RawMessageDelivery="true"

# Everything else goes to config sync (provisioning)
FILTER_CONFIG='{"event_type": [{"anything-but": ["TRANSFORM_EVENT", "COMPUTE_TRANSFORM_EVENT", "TRANSFORM_COMPLETED", "DELIVERY_COMPLETED", "DELIVER_EVENT", "notification.triggered"]}]}'
awslocal sns subscribe \
    --topic-arn $EDI_OUTBOX_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_CONFIG_ARN \
    --attributes FilterPolicy="$FILTER_CONFIG",FilterPolicyScope="MessageBody",RawMessageDelivery="true"

echo "LocalStack SQS queues and SNS topics created successfully."
