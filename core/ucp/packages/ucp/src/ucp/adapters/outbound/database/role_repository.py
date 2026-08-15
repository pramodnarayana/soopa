import json
import os
import uuid
from typing import Any

import structlog
from platform_orm.models import Role as OrmRole
from platform_orm.models import UserRole
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox

from ucp.core.exceptions import IdempotencyConflictError, ResourceNotFoundError
from ucp.domain.events.role_events import UserRoleAssignedEvent
from ucp.domain.models.authorization import Role as DomainRole
from ucp.ports.outbound.role_repository import IRoleRepository

logger = structlog.get_logger(__name__)


class PostgresRoleRepository(IRoleRepository):
    """
    PostgreSQL adapter for the Role Repository.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, role_id: str) -> DomainRole | None:
        stmt = select(OrmRole).where(OrmRole.id == role_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return DomainRole(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            capabilities=list(row.capabilities) if row.capabilities else [],
        )

    async def get_user_capabilities(self, tenant_id: str | None, user_id: str) -> set[str]:
        """
        Queries the database for all roles assigned to the user within the given tenant,
        and aggregates their capabilities into a unified set.
        """
        bound_logger = logger.bind(tenant_id=tenant_id, user_id=user_id)
        bound_logger.debug("role_repo.get_user_capabilities.started")

        tenant_filter: Any
        if tenant_id is None:
            tenant_filter = UserRole.tenant_id.is_(None)
        else:
            tenant_filter = UserRole.tenant_id == tenant_id

        stmt = (
            select(OrmRole.capabilities)
            .join(UserRole, OrmRole.id == UserRole.role_id)
            .where(
                tenant_filter,
                UserRole.user_id == user_id,
            )
        )

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        # Flatten the list of lists into a single unique set of capabilities
        capabilities: set[str] = set()
        for caps in rows:
            if caps:
                capabilities.update(caps)

        bound_logger.debug(
            "role_repo.get_user_capabilities.completed",
            roles_resolved=len(rows),
            capabilities_count=len(capabilities),
        )

        return capabilities

    async def save(self, role: DomainRole) -> None:
        stmt = select(OrmRole).where(OrmRole.id == role.id)
        result = await self.session.execute(stmt)
        orm_role = result.scalar_one_or_none()

        if orm_role:
            orm_role.name = role.name
            orm_role.description = role.description
            orm_role.capabilities = role.capabilities
        else:
            orm_role = OrmRole(
                id=role.id,
                tenant_id=role.tenant_id,
                name=role.name,
                description=role.description,
                capabilities=role.capabilities,
            )
            self.session.add(orm_role)

        self._flush_events(role)

    async def assign_user_role(self, tenant_id: str | None, user_id: str, role_id: str) -> None:
        bound_logger = logger.bind(tenant_id=tenant_id, user_id=user_id, role_id=role_id)
        bound_logger.info("role_repo.assign_user_role.started")

        user_role_id = f"urol_{uuid.uuid4().hex[:16]}"
        user_role = UserRole(
            id=user_role_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role_id=role_id,
        )
        self.session.add(user_role)
        try:
            await self.session.flush()
        except IntegrityError as e:
            constraint_name = (
                getattr(e.orig, "constraint_name", None) if hasattr(e, "orig") else None
            )
            logger.exception(
                "role_repo.assign_user_role.integrity_error",
                tenant_id=tenant_id,
                user_id=user_id,
                role_id=role_id,
                constraint_name=constraint_name,
                reason=str(e.orig) if hasattr(e, "orig") else str(e),
            )
            # Check for unique violation on user_role assignment
            if (
                constraint_name
                and "user_role" in constraint_name
                and "unique" in constraint_name.lower()
            ):
                raise IdempotencyConflictError(
                    f"Role '{role_id}' is already assigned to user '{user_id}' in tenant '{tenant_id}'."
                ) from e
            # Foreign key violations indicate missing user or role
            raise ResourceNotFoundError(
                f"Cannot assign role: User '{user_id}' or Role '{role_id}' not found."
            ) from e

        # Emit Outbox Event directly since we aren't loading an AggregateRoot
        event = UserRoleAssignedEvent(user_id=user_id, role_id=role_id)
        outbox_event = ControlPlaneOutbox(
            id=f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}",
            idempotency_key=f"{event.event_name}_{user_id}_{role_id}_{user_role_id}",
            tenant_id=tenant_id,
            event_type=event.event_name,
            payload=json.loads(event.model_dump_json()),
        )
        self.session.add(outbox_event)

        bound_logger.info("role_repo.assign_user_role.completed")

    def _flush_events(self, role: DomainRole, idempotency_key: str | None = None) -> None:
        for index, event in enumerate(role.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name

            payload_dict = json.loads(event.model_dump_json())
            tenant_id = (
                getattr(event, "tenant_id", None)
                or payload_dict.get("tenant_id", None)
                or role.tenant_id
            )

            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else getattr(event, "id", f"{event_name}_{role.id}_{index}")
            )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
            )
            self.session.add(outbox_event)

        role.clear_domain_events()
