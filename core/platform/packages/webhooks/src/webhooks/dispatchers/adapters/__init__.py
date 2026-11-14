"""Adapters for webhook dispatchers."""

from webhooks.dispatchers.adapters.http.resilient_dispatcher import ResilientWebhookDispatcher

__all__ = ["ResilientWebhookDispatcher"]
