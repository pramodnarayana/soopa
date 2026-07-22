#!/bin/bash
echo "Initializing LocalStack resources..."

# Create EDI Provisioning Queue for temporary standalone compatibility
awslocal sqs create-queue \
  --queue-name edi-provisioning.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=true

echo "LocalStack resources initialized successfully."
