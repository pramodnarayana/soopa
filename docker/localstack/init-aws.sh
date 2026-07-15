#!/bin/bash
echo "Initializing LocalStack S3 Bucket..."

# awslocal is the LocalStack wrapper for aws-cli
awslocal s3 mb s3://edi-as2-payloads
awslocal s3api put-bucket-acl --bucket edi-as2-payloads --acl public-read

echo "Initializing LocalStack SQS Queues..."



# Create Data Plane CDC Queues and DLQs
awslocal sqs create-queue --queue-name TransformOrchestrationQueue-DLQ
TRANSFORM_DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url http://localhost:4566/000000000000/TransformOrchestrationQueue-DLQ --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
awslocal sqs create-queue --queue-name TransformOrchestrationQueue --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$TRANSFORM_DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

awslocal sqs create-queue --queue-name DeliverQueue-DLQ
DELIVER_DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url http://localhost:4566/000000000000/DeliverQueue-DLQ --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
awslocal sqs create-queue --queue-name DeliverQueue --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DELIVER_DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

# Create Control Plane CDC Queues and DLQs
awslocal sqs create-queue --queue-name ProvisioningQueue-DLQ
PROVISIONING_DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url http://localhost:4566/000000000000/ProvisioningQueue-DLQ --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
awslocal sqs create-queue --queue-name ProvisioningQueue --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$PROVISIONING_DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

echo "LocalStack Initialization Complete."
