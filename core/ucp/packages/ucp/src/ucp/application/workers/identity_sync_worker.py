# DEPRECATED: This file violates Hexagonal Architecture by mixing SQS polling
# with Identity Sync business logic.
# It has been refactored into:
# - adapters/inbound/sqs_ucp_event_listener.py
# - application/services/identity_sync_service.py
# - ports/identity_provider.py
