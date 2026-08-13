import asyncio
import logging
import sys
import uuid

from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.bootstrap.container import Container
from ucp.core.container import _async_session_maker
from ucp.core.exceptions import IdentityProviderError
from ucp.ports.outbound.organization_provider import IOrganizationProvider
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider

logger = logging.getLogger(__name__)


class OutboxRelayWorker:
    def __init__(
        self,
        outbox_repo: PostgresOutboxRepository,
        org_provider: IOrganizationProvider,
        user_provider: IUserIdentityProvider,
    ):
        self.outbox_repo = outbox_repo
        self.org_provider = org_provider
        self.user_provider = user_provider
        self.worker_id = str(uuid.uuid4())

    async def run(self, max_iterations: int | None = None):
        logger.info(f"Starting Outbox Relay Worker (ID: {self.worker_id})")
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            try:
                # 1. Sweep stuck events
                await self.outbox_repo.sweep_stuck_events(lock_lease_ms=30000)

                # 2. Claim events
                events = await self.outbox_repo.claim_next_events(
                    worker_id=self.worker_id, limit=50, lock_lease_ms=30000
                )

                if not events:
                    await asyncio.sleep(2)
                    iterations += 1
                    continue

                for event in events:
                    try:
                        await self.process_event(event)
                        await self.outbox_repo.mark_completed(event.id, self.worker_id)
                    except Exception as e:
                        logger.exception(f"Failed to process event {event.id}")
                        await self.outbox_repo.mark_failed(event.id, self.worker_id, str(e))
            except Exception:
                logger.exception("Error in Outbox Relay Worker loop")
                await asyncio.sleep(5)

            iterations += 1

    async def process_event(self, event):  # noqa: C901
        logger.info(f"Processing event: {event.event_type} ({event.id})")

        if event.event_type == "TenantProvisioned":
            try:
                org_id, _ = await self.org_provider.create_organization(event.payload["name"])
            except IdentityProviderError as e:
                if e.status_code == 409:
                    # Basic idempotency / conflict handling for existing orgs
                    logger.warning(
                        f"Organization {event.payload['name']} already exists in IDP. "
                        f"Search logic needed to retrieve org_id."
                    )
                raise

            async with _async_session_maker() as session:
                uow = SqlAlchemyUcpUnitOfWork(session)
                async with uow:
                    tenant = await uow.tenant_repo.find_by_id(event.tenant_id)
                    if tenant and not tenant.idp_tenant_id:
                        tenant.set_idp_tenant_id(org_id)
                        await uow.tenant_repo.save(tenant)
                        await uow.commit()

        elif event.event_type == "TenantDeleted":
            await self.org_provider.delete_organization(event.payload["org_id"])

        elif event.event_type == "TenantNameUpdated":
            await self.org_provider.update_organization_name(
                org_id=event.payload["org_id"], name=event.payload["name"]
            )

        elif event.event_type == "TenantStatusToggled":
            await self.org_provider.toggle_organization_status(
                org_id=event.payload["org_id"], active=event.payload["active"]
            )

        elif event.event_type == "UserInvited":
            idp_user_id = None
            try:
                idp_user_id = await self.user_provider.create_user(
                    org_id=event.payload["org_id"],
                    email=event.payload["email"],
                    first_name=event.payload["first_name"],
                    last_name=event.payload["last_name"],
                )
            except IdentityProviderError as e:
                if e.status_code == 409:
                    logger.warning(
                        f"User {event.payload['email']} already exists in IDP. "
                        f"Search logic needed to retrieve user_id."
                    )
                raise

            await self.user_provider.assign_tenant_role(
                user_id=idp_user_id,
                org_id=event.payload["org_id"],
                role=event.payload["role"],
            )

            async with _async_session_maker() as session:
                uow = SqlAlchemyUcpUnitOfWork(session)
                async with uow:
                    user = await uow.user_repo.find_by_email(event.payload["email"])
                    if user and not user.idp_user_id:
                        user.set_idp_user_id(idp_user_id)
                        await uow.user_repo.save(user)
                        await uow.commit()

        elif event.event_type == "UserUpdated":
            await self.user_provider.update_user_profile(
                user_id=event.payload["idp_user_id"],
                org_id=event.payload["org_id"],
                first_name=event.payload["first_name"],
                last_name=event.payload["last_name"],
            )
            await self.user_provider.update_tenant_role(
                user_id=event.payload["idp_user_id"],
                org_id=event.payload["org_id"],
                role=event.payload["role"],
            )

        elif event.event_type == "UserStatusToggled":
            await self.user_provider.toggle_user_status(
                user_id=event.payload["idp_user_id"],
                org_id=event.payload["org_id"],
                action=event.payload["action"],
            )

        elif event.event_type == "UserDeleted":
            await self.user_provider.delete_user(event.payload["idp_user_id"])

        else:
            logger.warning(f"Unknown event type: {event.event_type}")


async def main():
    logging.basicConfig(level=logging.INFO)

    container = Container()
    container.wire(modules=[sys.modules[__name__]])

    worker = OutboxRelayWorker(
        outbox_repo=container.outbox_repo(),
        org_provider=container.org_provider(),
        user_provider=container.user_provider(),
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
