#!/bin/bash
echo "Initializing LocalStack SQS queues and SNS topics..."

# 1. Create SNS Topics
awslocal sns create-topic --name ucp-events-topic.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name edi-events-topic.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name identity-events-topic.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true

# 2. Create SQS Queues
awslocal sqs create-queue --queue-name ucp-jobs-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp-jobs.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name ucp-events-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp-events.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name identity-events-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name identity-events.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-config-sync-queue-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-config-sync-queue.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-transform-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-transform.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-lifecycle-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-lifecycle.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-orchestrator-jobs-dlq
awslocal sqs create-queue --queue-name edi-orchestrator-jobs
awslocal sqs create-queue --queue-name edi-deliver-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-deliver.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-priority-notifications-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-priority-notifications.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

# 3. Get ARNs
UCP_EVENTS_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:ucp-events-topic.fifo --query 'Attributes.TopicArn' --output text)
EDI_EVENTS_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:edi-events-topic.fifo --query 'Attributes.TopicArn' --output text)
IDENTITY_EVENTS_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:identity-events-topic.fifo --query 'Attributes.TopicArn' --output text)

UCP_EVENTS_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp-events.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
IDENTITY_EVENTS_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/identity-events.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

EDI_TRANSFORM_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-transform.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_LIFECYCLE_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-lifecycle.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_DELIVER_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-deliver.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_CONFIG_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-config-sync-queue.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)


# 4. Subscribe Queues to Topics

awslocal sns subscribe --topic-arn $UCP_EVENTS_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_EVENTS_ARN
awslocal sns subscribe --topic-arn $IDENTITY_EVENTS_TOPIC_ARN --protocol sqs --notification-endpoint $IDENTITY_EVENTS_ARN

# Setup Data Plane SNS to SQS Subscriptions with Payload Filtering
awslocal sns subscribe \
    --topic-arn $EDI_EVENTS_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_TRANSFORM_ARN \
    --attributes '{"FilterPolicy": "{\"eventType\": [\"TRANSFORM_EVENT\", \"COMPUTE_TRANSFORM_EVENT\"]}", "FilterPolicyScope": "MessageBody", "RawMessageDelivery": "true"}'

awslocal sns subscribe \
    --topic-arn $EDI_EVENTS_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_LIFECYCLE_ARN \
    --attributes '{"FilterPolicy": "{\"eventType\": [\"TRANSFORM_COMPLETED\", \"DELIVERY_COMPLETED\"]}", "FilterPolicyScope": "MessageBody", "RawMessageDelivery": "true"}'

awslocal sns subscribe \
    --topic-arn $EDI_EVENTS_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_DELIVER_ARN \
    --attributes '{"FilterPolicy": "{\"eventType\": [\"DELIVER_EVENT\"]}", "FilterPolicyScope": "MessageBody", "RawMessageDelivery": "true"}'

# Everything else goes to config sync (provisioning)
awslocal sns subscribe \
    --topic-arn $EDI_EVENTS_TOPIC_ARN \
    --protocol sqs \
    --notification-endpoint $EDI_CONFIG_ARN \
    --attributes '{"FilterPolicy": "{\"eventType\": [{\"anything-but\": [\"TRANSFORM_EVENT\", \"COMPUTE_TRANSFORM_EVENT\", \"TRANSFORM_COMPLETED\", \"DELIVERY_COMPLETED\", \"DELIVER_EVENT\", \"notification.triggered\"]}]}", "FilterPolicyScope": "MessageBody", "RawMessageDelivery": "true"}'

echo "LocalStack SQS queues and SNS topics created successfully."
