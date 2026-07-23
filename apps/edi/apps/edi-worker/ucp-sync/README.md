# UCP Sync Worker

This worker is responsible for synchronizing Identity events (Tenants, API Keys) from UCP into the EDI global database.

It polls the `ucp.events.fifo` queue and ingests the events into `edi_global_db`. Tenant events trigger the internal EDI provisioning pipeline to cascade those changes to the shards, while API-key events are only ingested into the global database for authentication purposes.
