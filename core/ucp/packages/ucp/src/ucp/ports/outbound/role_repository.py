import abc

from ucp.domain.models.authorization import Role


class IRoleRepository(abc.ABC):
    """
    Outbound port for managing Tenant Roles and resolving User Capabilities.
    """

    @abc.abstractmethod
    async def get_user_capabilities(self, tenant_id: str | None, user_id: str) -> set[str]:
        """
        Fetch the unified set of dynamic capabilities assigned to a user within a specific tenant.
        This resolves all roles assigned to the user, extracts their capabilities, and aggregates them into a unique set.
        """

    @abc.abstractmethod
    @abc.abstractmethod
    async def get_by_id(self, role_id: str) -> Role | None:
        """Fetch a role by its ID."""

    @abc.abstractmethod
    async def get_global_role_by_name(self, name: str) -> Role | None:
        """Fetch a global role (tenant_id is NULL) by its name."""

    @abc.abstractmethod
    async def save(self, role: Role) -> None:
        """Persists a new or updated role."""

    @abc.abstractmethod
    async def assign_user_role(self, tenant_id: str | None, user_id: str, role_id: str) -> None:
        """
        Assign a role to a user.
        """

    @abc.abstractmethod
    async def remove_user_roles(self, tenant_id: str | None, user_id: str) -> None:
        """
        Removes all roles assigned to a user within a specific tenant context.
        """

    @abc.abstractmethod
    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        """
        Checks if a user has any tenant memberships by looking for any UserRole assigned to them.
        """
