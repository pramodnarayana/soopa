# EDI Delivery Worker

This service is a dedicated delivery worker that consumes `EXECUTE_DELIVERY_COMMAND` messages
from the EDI deliver SQS queue and delegates final-mile delivery processing to the appropriate
pipeline strategy (AS2, SFTP, or Webhook), emitting a `DELIVERY_COMPLETED` event on success.
