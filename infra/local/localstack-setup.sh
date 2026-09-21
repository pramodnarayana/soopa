#!/bin/bash
set -eo pipefail

echo "Initializing LocalStack SQS queues and SNS topics..."

# 1. Create SNS Topics
awslocal sns create-topic --name platform-events-topic.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name edi-data-plane-topic

# 2. Create SQS Queues
create_queue_with_dlq() {
    local source_queue=$1
    local dlq=$2
    local fifo=$3
    local dlq_url
    local dlq_arn
    local queue_attributes

    if [ "$fifo" = "true" ]; then
        awslocal sqs create-queue --queue-name "$dlq" --attributes FifoQueue=true,ContentBasedDeduplication=true
    else
        awslocal sqs create-queue --queue-name "$dlq"
    fi

    dlq_url=$(awslocal sqs get-queue-url --queue-name "$dlq" --query 'QueueUrl' --output text)
    dlq_arn=$(awslocal sqs get-queue-attributes --queue-url "$dlq_url" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

    local queue_arn="arn:aws:sqs:us-east-1:000000000000:$source_queue"
    local policy="{\\\"Version\\\":\\\"2012-10-17\\\",\\\"Statement\\\":[{\\\"Effect\\\":\\\"Allow\\\",\\\"Principal\\\":\\\"*\\\",\\\"Action\\\":\\\"sqs:SendMessage\\\",\\\"Resource\\\":\\\"$queue_arn\\\",\\\"Condition\\\":{\\\"ArnLike\\\":{\\\"aws:SourceArn\\\":\\\"arn:aws:sns:us-east-1:000000000000:*\\\"}}}]}"

    if [ "$fifo" = "true" ]; then
        queue_attributes=$(printf '{"FifoQueue":"true","ContentBasedDeduplication":"true","RedrivePolicy":"{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":\\"5\\"}","Policy":"%s"}' "$dlq_arn" "$policy")
    else
        queue_attributes=$(printf '{"RedrivePolicy":"{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":\\"5\\"}","Policy":"%s"}' "$dlq_arn" "$policy")
    fi

    awslocal sqs create-queue --queue-name "$source_queue" --attributes "$queue_attributes"
}

create_queue_with_dlq ucp-jobs.fifo ucp-jobs-dlq.fifo true
create_queue_with_dlq notification-jobs.fifo notification-jobs-dlq.fifo true
create_queue_with_dlq identity-jobs.fifo identity-jobs-dlq.fifo true
create_queue_with_dlq ucp-events.fifo ucp-events-dlq.fifo true
create_queue_with_dlq identity-events.fifo identity-events-dlq.fifo true
create_queue_with_dlq edi-config-sync-queue.fifo edi-config-sync-queue-dlq.fifo true
create_queue_with_dlq edi-orchestrator edi-orchestrator-dlq false
create_queue_with_dlq edi-compute edi-compute-dlq false
create_queue_with_dlq edi-data-plane-jobs.fifo edi-data-plane-jobs-dlq.fifo true
create_queue_with_dlq edi-control-plane-jobs.fifo edi-control-plane-jobs-dlq.fifo true
create_queue_with_dlq edi-deliver edi-deliver-dlq false
create_queue_with_dlq edi-priority-notifications.fifo edi-priority-notifications-dlq.fifo true
create_queue_with_dlq email-channel.fifo email-channel-dlq.fifo true

# 3. Get ARNs
PLATFORM_EVENTS_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:platform-events-topic.fifo --query 'Attributes.TopicArn' --output text)
EDI_DATA_PLANE_TOPIC_ARN=$(awslocal sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:000000000000:edi-data-plane-topic --query 'Attributes.TopicArn' --output text)

UCP_EVENTS_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ucp-events.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
IDENTITY_EVENTS_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/identity-events.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

EDI_ORCHESTRATOR_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-orchestrator --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_COMPUTE_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-compute --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_DELIVER_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-deliver --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
EDI_CONFIG_ARN=$(awslocal sqs get-queue-attributes --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-config-sync-queue.fifo --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)


# 4. Subscribe Queues to Topics

awslocal sns subscribe --topic-arn "$PLATFORM_EVENTS_TOPIC_ARN" --protocol sqs --notification-endpoint "$UCP_EVENTS_ARN" \
    --attributes '{"FilterPolicy": "{\"event_type\": [{\"prefix\": \"app.\"}, {\"prefix\": \"tenant.\"}]}", "RawMessageDelivery": "true"}'

# Identity worker needs to listen to UCP events to provision tenants and sync users
awslocal sns subscribe --topic-arn "$PLATFORM_EVENTS_TOPIC_ARN" --protocol sqs --notification-endpoint "$IDENTITY_EVENTS_ARN" \
    --attributes '{"FilterPolicy": "{\"event_type\": [{\"prefix\": \"tenant.\"}, {\"prefix\": \"app.\"}, {\"prefix\": \"user.\"}]}", "RawMessageDelivery": "true"}'

# Data Plane pipeline queues: Debezium CDC publishes all outbox events to the new edi-data-plane-topic.
# Each queue subscribes with a filter on its specific event_type(s).
awslocal sns subscribe --topic-arn "$EDI_DATA_PLANE_TOPIC_ARN" --protocol sqs --notification-endpoint "$EDI_ORCHESTRATOR_ARN" \
    --attributes '{"FilterPolicy": "{\"event_type\": [\"TRANSFORMATION_REQUESTED\", \"TRANSFORMATION_SUCCESSFUL\", \"TRANSFORMATION_FAILED\", \"DELIVERY_REQUESTED\", \"DELIVERY_SUCCESSFUL\", \"DELIVERY_FAILED\"]}", "RawMessageDelivery": "true"}'

awslocal sns subscribe --topic-arn "$EDI_DATA_PLANE_TOPIC_ARN" --protocol sqs --notification-endpoint "$EDI_COMPUTE_ARN" \
    --attributes '{"FilterPolicy": "{\"event_type\": [\"COMPUTE_TRANSFORMATION_COMMAND\"]}", "RawMessageDelivery": "true"}'

awslocal sns subscribe --topic-arn "$EDI_DATA_PLANE_TOPIC_ARN" --protocol sqs --notification-endpoint "$EDI_DELIVER_ARN" \
    --attributes '{"FilterPolicy": "{\"event_type\": [\"EXECUTE_DELIVERY_COMMAND\"]}", "RawMessageDelivery": "true"}'

# EDI Config Sync: provisioning + webhook events (published by the CP outbox relay)
awslocal sns subscribe --topic-arn "$PLATFORM_EVENTS_TOPIC_ARN" --protocol sqs --notification-endpoint "$EDI_CONFIG_ARN" \
    --attributes '{"FilterPolicy": "{\"event_type\": [{\"prefix\": \"webhook.\"}, {\"prefix\": \"edi.\"}]}", "RawMessageDelivery": "true"}'



echo "LocalStack SQS queues and SNS topics created successfully."
