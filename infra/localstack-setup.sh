#!/bin/bash
echo "Initializing LocalStack SQS queues and SNS topics..."

# 1. Create SNS Topics
awslocal sns create-topic --name ucp-tenant-events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name ucp-user-events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true

# 2. Create SQS Queues
awslocal sqs create-queue --queue-name ucp-identity-sync-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp-identity-sync.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name ucp.events-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name ucp.events.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-tenant-sync-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-tenant-sync.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-config-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-config.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-transform-orchestration-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-transform-orchestration.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-transform-compute-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-transform-compute.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-deliver-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-deliver.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

awslocal sqs create-queue --queue-name edi-priority-notifications-dlq.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi-priority-notifications.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

# 3. Get ARNs
TENANT_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:ucp-tenant-events.fifo --query 'Attributes.TopicArn' --output text)
USER_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:ucp-user-events.fifo --query 'Attributes.TopicArn' --output text)

UCP_ID_SYNC_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp-identity-sync.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
UCP_EVENTS_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp.events.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

# 4. Subscribe Queues to Topics
awslocal sns subscribe --topic-arn $TENANT_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_ID_SYNC_ARN
awslocal sns subscribe --topic-arn $USER_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_ID_SYNC_ARN

awslocal sns subscribe --topic-arn $TENANT_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_EVENTS_ARN
awslocal sns subscribe --topic-arn $USER_TOPIC_ARN --protocol sqs --notification-endpoint $UCP_EVENTS_ARN

echo "LocalStack SQS queues and SNS topics created successfully."
