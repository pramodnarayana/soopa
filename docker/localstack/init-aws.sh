#!/bin/bash
echo "Initializing LocalStack S3 Bucket..."

# awslocal is the LocalStack wrapper for aws-cli
awslocal s3 mb s3://edi-as2-payloads
awslocal s3api put-bucket-acl --bucket edi-as2-payloads --acl public-read

echo "Initializing LocalStack SQS Queues..."

# Create Dead Letter Queue first
awslocal sqs create-queue --queue-name EdiTransformerQueue-DLQ
DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url http://localhost:4566/000000000000/EdiTransformerQueue-DLQ --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

# Create main queue with redrive policy
awslocal sqs create-queue --queue-name EdiTransformerQueue --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

echo "LocalStack Initialization Complete."
