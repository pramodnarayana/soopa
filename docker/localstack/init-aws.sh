#!/bin/bash
echo "Initializing LocalStack S3 Bucket..."

# awslocal is the LocalStack wrapper for aws-cli
awslocal s3 mb s3://edi-as2-payloads
awslocal s3api put-bucket-acl --bucket edi-as2-payloads --acl public-read

echo "Initializing LocalStack SQS Queues..."
awslocal sqs create-queue --queue-name EdiTransformerQueue

echo "LocalStack Initialization Complete."
