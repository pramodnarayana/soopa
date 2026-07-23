#!/bin/bash
echo "Initializing LocalStack resources for Fan-Out Architecture..."

# 1. Create SNS Topics (UCP Control Plane)
awslocal sns create-topic --name ucp.tenant.events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true
awslocal sns create-topic --name ucp.user.events.fifo --attributes FifoTopic=true,ContentBasedDeduplication=true

# 2. Create SQS Queues (EDI Data Plane)
awslocal sqs create-queue --queue-name edi.tenant.sync.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name edi.user.sync.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true

# 3. Set Queue Policies to allow SNS to send messages
awslocal sqs set-queue-attributes \
    --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi.tenant.sync.fifo \
    --attributes Policy='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"sns.amazonaws.com"},"Action":"sqs:SendMessage","Resource":"arn:aws:sqs:us-east-1:000000000000:edi.tenant.sync.fifo","Condition":{"ArnEquals":{"aws:SourceArn":"arn:aws:sns:us-east-1:000000000000:ucp.tenant.events.fifo"}}}]}'

awslocal sqs set-queue-attributes \
    --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi.user.sync.fifo \
    --attributes Policy='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"sns.amazonaws.com"},"Action":"sqs:SendMessage","Resource":"arn:aws:sqs:us-east-1:000000000000:edi.user.sync.fifo","Condition":{"ArnEquals":{"aws:SourceArn":"arn:aws:sns:us-east-1:000000000000:ucp.user.events.fifo"}}}]}'

# 4. Subscribe SQS Queues to SNS Topics
awslocal sns subscribe \
    --topic-arn arn:aws:sns:us-east-1:000000000000:ucp.tenant.events.fifo \
    --protocol sqs \
    --notification-endpoint arn:aws:sqs:us-east-1:000000000000:edi.tenant.sync.fifo

awslocal sns subscribe \
    --topic-arn arn:aws:sns:us-east-1:000000000000:ucp.user.events.fifo \
    --protocol sqs \
    --notification-endpoint arn:aws:sqs:us-east-1:000000000000:edi.user.sync.fifo

echo "LocalStack resources initialized successfully."
