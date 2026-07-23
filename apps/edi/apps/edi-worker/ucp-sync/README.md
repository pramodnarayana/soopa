# UCP Sync Worker

This worker is responsible for synchronizing Identity events (Tenants, API Keys) from UCP into the EDI global database.

It polls the `ucp.events.fifo` queue, ingests the events into `edi_global_db`, and triggers the internal EDI provisioning pipeline to cascade those changes to the shards.
