#!/bin/bash
echo "Initializing LocalStack SQS queues..."
awslocal sqs create-queue --queue-name edi-provisioning.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
awslocal sqs create-queue --queue-name idp-provisioning.fifo --attributes FifoQueue=true,ContentBasedDeduplication=true
echo "LocalStack SQS queues created successfully."
