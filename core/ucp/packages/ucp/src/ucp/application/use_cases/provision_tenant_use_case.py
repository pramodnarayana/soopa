from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.utils import generate_id

from ucp.domain.exceptions import SlugExhaustedError, UcpError
from ucp.domain.services.slug_service import try_generate_slug
from ucp.domain.tenant import Tenant
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class ProvisionTenantCommand:
    name: str


logger = structlog.get_logger(__name__)

# Maximum number of slug variants to try before giving up.
# e.g. "acme-corp", "acme-corp-2", ..., "acme-corp-10"
_MAX_SLUG_ATTEMPTS = 10


class ProvisionTenantUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, command: ProvisionTenantCommand, idempotency_key: str | None = None
    ) -> Result[Tenant, UcpError]:
        slug_res = try_generate_slug(command.name)
        if slug_res.is_err:
            err = slug_res.unwrap_err()
            logger.error(
                "provision_tenant.invalid_name",
                tenant_name=command.name,
                code=err.code.value,
                reason=err.message,
            )
            return Result.fail(err)

        base_slug = slug_res.unwrap()
        local_id = generate_id(Tenant.ID_PREFIX)

        logger.info(
            "provision_tenant.started",
            tenant_id=local_id,
            tenant_name=command.name,
            base_slug=base_slug,
            idempotency_key=idempotency_key,
        )

        # Optimistic insert with conflict-safe slug retry via TenantRepositoryPort.
        for attempt in range(_MAX_SLUG_ATTEMPTS):
            slug = base_slug if attempt == 0 else f"{base_slug}-{attempt + 1}"

            async with self.uow:
                create_res = Tenant.create(
                    id=local_id,
                    name=command.name,
                    slug=slug,
                    idp_tenant_id=None,
                    subscriptions=[],
                )
                if create_res.is_err:
                    err = create_res.unwrap_err()
                    logger.error(
                        "provision_tenant.validation_failed",
                        tenant_id=local_id,
                        code=err.code.value,
                        reason=err.message,
                    )
                    return create_res

                tenant = create_res.unwrap()
                inserted = await self.uow.tenant_repo.insert_if_slug_available(
                    tenant, idempotency_key
                )
                if not inserted:
                    logger.warning(
                        "provision_tenant.slug_conflict",
                        slug=slug,
                        attempt=attempt,
                        tenant_name=command.name,
                    )
                    continue

                await self.uow.commit()

            logger.info(
                "provision_tenant.completed",
                tenant_id=tenant.id,
                slug=slug,
                attempt=attempt,
            )
            return Result.ok(tenant)

        logger.error(
            "provision_tenant.slug_exhausted",
            tenant_name=command.name,
            base_slug=base_slug,
            max_attempts=_MAX_SLUG_ATTEMPTS,
        )
        return Result.fail(SlugExhaustedError.for_name(command.name, _MAX_SLUG_ATTEMPTS))
