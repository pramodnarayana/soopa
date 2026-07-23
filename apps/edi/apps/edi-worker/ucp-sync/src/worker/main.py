import asyncio
import json
import logging
from typing import Any

import aioboto3
from botocore.exceptions import ClientError
from config.settings import get_settings
from database.connection import DatabaseRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class UcpEventMessage(BaseModel):
    idempotencyKey: str
    tenantId: str
    eventType: str
    payload: dict[str, Any]

class UcpSyncWorkerService:
    def __init__(self, db_router: DatabaseRouter, sqs_client: Any, queue_url: str, sync_queue_url: str):
        self.db_router = db_router
        self.sqs_client = sqs_client
        self.queue_url = queue_url
        self.sync_queue_url = sync_queue_url

    async def _handle_tenant_created(self, payload: dict[str, Any], global_session: AsyncSession) -> None:
        tenant_id = int(payload["id"])
        name = payload["name"]

        logger.info(f"Syncing tenant {tenant_id} into edi_global_db")
        await global_session.execute(
            text("""
                INSERT INTO tenants (id, name, status, created_at, updated_at)
                VALUES (:id, :name, 'active', NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET name = :name, updated_at = NOW()
            """),
            {"id": tenant_id, "name": name}
        )
        await global_session.commit()

        # Dispatch to edi.tenant.sync.fifo
        logger.info(f"Dispatching sync event for tenant {tenant_id} to edi.tenant.sync.fifo")
        try:
            await self.sqs_client.send_message(
                QueueUrl=self.sync_queue_url,
                MessageBody=json.dumps({"tenant_id": tenant_id}),
                MessageGroupId=str(tenant_id),
                MessageDeduplicationId=f"sync_{tenant_id}_{asyncio.get_event_loop().time()}"
            )
        except Exception as e:
            logger.error(f"Failed to dispatch sync message for tenant {tenant_id}: {e}")
            raise

    async def _handle_api_key_created(self, payload: dict[str, Any], global_session: AsyncSession) -> None:
        client_id = payload["id"]
        tenant_id = int(payload["tenantId"])
        name = payload["name"]
        key_hash = payload["keyHash"]

        logger.info(f"Syncing API Key {client_id} into edi_global_db")
        # We assume api_tokens has id (UUID), tenant_id, name, client_id, client_secret (hashed), active
        # Notice we map keyHash to client_secret.
        await global_session.execute(
            text("""
                INSERT INTO api_tokens (id, tenant_id, name, client_id, client_secret, active)
                VALUES (gen_random_uuid(), :tenant_id, :name, :client_id, :key_hash, true)
                ON CONFLICT (client_id) DO NOTHING
            """),
            {"tenant_id": tenant_id, "name": name, "client_id": client_id, "key_hash": key_hash}
        )
        await global_session.commit()

    async def process_messages(self) -> None:
        try:
            response = await self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5,
            )

            messages = response.get("Messages", [])
            if not messages:
                return

            for msg in messages:
                receipt_handle = msg["ReceiptHandle"]
                body = msg["Body"]

                try:
                    # In SNS to SQS fanout, the actual event is wrapped inside the SNS "Message" field
                    sns_wrapper = json.loads(body)
                    event_str = sns_wrapper.get("Message", body) # Fallback to body if not SNS wrapped

                    event_data = json.loads(event_str)
                    parsed_event = UcpEventMessage(**event_data)

                    async for session in self.db_router.get_global_session():
                        if parsed_event.eventType == "tenant.provisioned":
                            await self._handle_tenant_created(parsed_event.payload, session)
                        elif parsed_event.eventType == "api_key.created":
                            await self._handle_api_key_created(parsed_event.payload, session)
                        else:
                            logger.info(f"Ignored event type: {parsed_event.eventType}")

                    # Delete message on success
                    await self.sqs_client.delete_message(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=receipt_handle
                    )
                except Exception as e:
                    logger.exception(f"Error processing message: {e}")
                    # Don't delete, let it go to DLQ
        except ClientError as e:
            logger.error(f"SQS ClientError: {e}")

async def run_worker(service: UcpSyncWorkerService) -> None:
    logger.info("Started UCP Sync Worker")
    while True:
        try:
            await service.process_messages()
        except Exception as e:
            logger.exception(f"Error in UCP sync loop: {e}")
            await asyncio.sleep(5)

async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    import os
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")

    session = aioboto3.Session()
    async with session.client("sqs", endpoint_url=endpoint_url) as sqs_client:
        # Resolve queue URLs (In a real environment, these would be passed via config)
        try:
            ucp_resp = await sqs_client.get_queue_url(QueueName="ucp.events.fifo")
            sync_resp = await sqs_client.get_queue_url(QueueName="edi.tenant.sync.fifo")

            service = UcpSyncWorkerService(
                db_router=db_router,
                sqs_client=sqs_client,
                queue_url=ucp_resp["QueueUrl"],
                sync_queue_url=sync_resp["QueueUrl"]
            )

            await run_worker(service)
        except Exception as e:
            logger.error(f"Initialization error: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
