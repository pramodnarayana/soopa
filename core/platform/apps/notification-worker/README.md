# notification-worker

Worker container for the Notification bounded context. Responsible for:

- Processing the notification outbox (dispatching notifications via email, in-app, Slack)
- Sweeping stuck/stale outbox entries for retry

This worker runs as a separate container from the Notification API, following the Shopify-style single-image / multiple-container deployment strategy.
