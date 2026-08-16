import os
from dataclasses import dataclass

import structlog

from ucp.core.exceptions import DuplicateEntityError, SlugExhaustedException
from ucp.domain.models.tenant import Tenant
from ucp.domain.services.slug_service import generate_slug
from ucp.ports.uow import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)

# Maximum number of slug variants to try before giving up.
# e.g. "acme-corp", "acme-corp-2", ..., "acme-corp-10"
_MAX_SLUG_ATTEMPTS = 10


@dataclass(frozen=True)
class ProvisionTenantCommand:
    """
    Immutable command object carrying the intent to provision a new tenant.

    This is a pure application-layer concept with no dependency on HTTP or
    serialisation frameworks. Routers map their HTTP DTOs into this command
    before invoking the use case.
    """

    name: str


class ProvisionTenantUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, command: ProvisionTenantCommand, idempotency_key: str | None = None
    ) -> Tenant:
        # NOTE: Tenant ID generation intentionally lives here (application layer)
        # because it requires os.urandom — a side-effectful infrastructure call.
        # A future improvement is a TenantId value object with a generate() factory.
        local_id = f"{Tenant.ID_PREFIX}_{os.urandom(12).hex()}"
        base_slug = generate_slug(command.name)

        logger.info(
            "provision_tenant.started",
            tenant_id=local_id,
            tenant_name=command.name,
            base_slug=base_slug,
            idempotency_key=idempotency_key,
        )

        # Optimistic insert with DB-level uniqueness retry.
        #
        # We do NOT pre-load all existing slugs (TOCTOU race condition).
        # Instead, we attempt an INSERT and retry with a numeric suffix on
        # UNIQUE constraint violations — letting the database be the final
        # authority. This is correct under concurrent provisioning.
        for attempt in range(_MAX_SLUG_ATTEMPTS):
            slug = base_slug if attempt == 0 else f"{base_slug}-{attempt + 1}"

            try:
                async with self.uow:
                    tenant = Tenant.create(
                        id=local_id,
                        name=command.name,
                        slug=slug,
                        idp_tenant_id=None,
                        subscriptions=[],
                    )

                    await self.uow.tenant_repo.save(tenant, idempotency_key)
                    await self.uow.commit()

                logger.info(
                    "provision_tenant.completed",
                    tenant_id=tenant.id,
                    slug=slug,
                    attempt=attempt,
                )
                return tenant

            except DuplicateEntityError as exc:
                # Only retry on the slug uniqueness constraint violation.
                # All other DuplicateEntityError constraints (e.g. name conflict) are re-raised.
                if exc.constraint_name == "tenants_slug_key":
                    logger.warning(
                        "provision_tenant.slug_conflict",
                        slug=slug,
                        attempt=attempt,
                        tenant_name=command.name,
                    )
                    continue

                logger.exception(
                    "provision_tenant.integrity_error",
                    tenant_id=local_id,
                    constraint_name=exc.constraint_name,
                    reason=str(exc),
                )
                raise

        logger.error(
            "provision_tenant.slug_exhausted",
            tenant_name=command.name,
            base_slug=base_slug,
            max_attempts=_MAX_SLUG_ATTEMPTS,
        )
        raise SlugExhaustedException(
            f"Could not allocate a unique slug for tenant name {command.name!r} "
            f"after {_MAX_SLUG_ATTEMPTS} attempts."
        )
