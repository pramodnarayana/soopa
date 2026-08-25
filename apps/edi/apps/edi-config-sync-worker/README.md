# Worker Service

This service contains two background workers:
1. **Provisioning Worker**: Polls the Global DB `outbox` for tenant/partner provisioning events, and applies them to the respective Tenant Shards.
2. **Data Worker**: Consumes translation and delivery events from SQS, delegating the domain logic to `libs/pipeline`.
