#!/bin/bash
set -eo pipefail

TOPOLOGY_FILE="/etc/localstack/init/ready.d/topology.json"

echo "Initializing LocalStack infrastructure from $TOPOLOGY_FILE..."

# Wait for localstack to be ready just in case
awslocal sns list-topics >/dev/null 2>&1 || true

# Helper to run python JSON parser
parse_json() {
    python3 -c "import sys, json; data=json.load(open('$TOPOLOGY_FILE')); print('\n'.join([json.dumps(x) for x in data.get('$1', [])]))"
}

IFS=$'\n'

# 1. Create S3 Buckets
echo "--- Provisioning S3 Buckets ---"
for row in $(parse_json "buckets"); do
    bucket_name=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('name', ''))" "$row")
    echo "Creating Bucket: $bucket_name"
    awslocal s3 mb "s3://$bucket_name" || true
done

# 2. Create Secrets Manager Secrets
echo "--- Provisioning Secrets ---"
for row in $(parse_json "secrets"); do
    secret_name=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('name', ''))" "$row")
    mock_value=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('mockValue', '{}'))" "$row")
    echo "Creating Secret: $secret_name"

    # Check if secret exists, otherwise create it
    if ! awslocal secretsmanager describe-secret --secret-id "$secret_name" >/dev/null 2>&1; then
        awslocal secretsmanager create-secret --name "$secret_name" --secret-string "$mock_value"
    else
        echo "Secret $secret_name already exists, updating..."
        awslocal secretsmanager update-secret --secret-id "$secret_name" --secret-string "$mock_value"
    fi
done

# 3. Create SNS Topics
echo "--- Provisioning SNS Topics ---"
for row in $(parse_json "topics"); do
    logical_topic_name=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('name', ''))" "$row")
    fifo=$(python3 -c "import sys, json; print(str(json.loads(sys.argv[1]).get('fifo', False)).lower())" "$row")

    if [ "$fifo" = "true" ]; then
        physical_topic_name="${logical_topic_name}.fifo"
        echo "Creating FIFO Topic: $physical_topic_name"
        awslocal sns create-topic --name "$physical_topic_name" --attributes FifoTopic=true,ContentBasedDeduplication=true
    else
        physical_topic_name="${logical_topic_name}"
        echo "Creating Standard Topic: $physical_topic_name"
        awslocal sns create-topic --name "$physical_topic_name"
    fi
done

# 4. Create SQS Queues
echo "--- Provisioning SQS Queues ---"
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

for row in $(parse_json "queues"); do
    logical_queue_name=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('name', ''))" "$row")
    fifo=$(python3 -c "import sys, json; print(str(json.loads(sys.argv[1]).get('fifo', False)).lower())" "$row")

    if [ "$fifo" = "true" ]; then
        physical_queue_name="${logical_queue_name}.fifo"
        dlq_name="${logical_queue_name}-dlq.fifo"
    else
        physical_queue_name="${logical_queue_name}"
        dlq_name="${logical_queue_name}-dlq"
    fi

    echo "Creating Queue: $physical_queue_name (FIFO=$fifo)"
    create_queue_with_dlq "$physical_queue_name" "$dlq_name" "$fifo"
done

# 5. Create Subscriptions
echo "--- Provisioning SNS Subscriptions ---"
for row in $(parse_json "subscriptions"); do
    logical_topic_name=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('topic', ''))" "$row")
    logical_queue_name=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('queue', ''))" "$row")
    filter_policy=$(python3 -c "import sys, json; print(json.dumps(json.loads(sys.argv[1]).get('filterPolicy', {})))" "$row")

    # We must determine if the topic/queue is FIFO to resolve the physical AWS name for subscription
    # Since subscriptions in topology.json don't have the fifo flag natively, we look it up in the JSON!
    topic_fifo=$(python3 -c "import sys, json; data=json.load(open('$TOPOLOGY_FILE')); print(str(next((t.get('fifo', False) for t in data.get('topics', []) if t.get('name') == '$logical_topic_name'), False)).lower())")
    queue_fifo=$(python3 -c "import sys, json; data=json.load(open('$TOPOLOGY_FILE')); print(str(next((q.get('fifo', False) for q in data.get('queues', []) if q.get('name') == '$logical_queue_name'), False)).lower())")

    if [ "$topic_fifo" = "true" ]; then
        physical_topic_name="${logical_topic_name}.fifo"
    else
        physical_topic_name="${logical_topic_name}"
    fi

    if [ "$queue_fifo" = "true" ]; then
        physical_queue_name="${logical_queue_name}.fifo"
    else
        physical_queue_name="${logical_queue_name}"
    fi

    topic_arn="arn:aws:sns:us-east-1:000000000000:$physical_topic_name"
    queue_url="http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/$physical_queue_name"
    queue_arn=$(awslocal sqs get-queue-attributes --queue-url "$queue_url" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

    # We must properly escape the filter_policy JSON for AWS CLI
    escaped_filter_policy=$(echo $filter_policy | sed 's/"/\\"/g')

    echo "Subscribing $physical_queue_name to $physical_topic_name..."
    awslocal sns subscribe --topic-arn "$topic_arn" --protocol sqs --notification-endpoint "$queue_arn" \
        --attributes "{\"FilterPolicy\": \"$escaped_filter_policy\", \"RawMessageDelivery\": \"true\"}"
done

echo "LocalStack initialization successfully completed from topology.json!"
