from .ports import IIdentityRepository


class ResolveTenantUseCase:
    """
    Pure Application Use Case for resolving a user's JWT email into a Tenant ID.
    Handles Just-In-Time (JIT) provisioning if the user is logging in for the first time.
    """

    def __init__(self, repository: IIdentityRepository):
        self.repository = repository

    async def execute(self, email: str, name: str) -> int:
        """
        Resolves a user's email to a tenant ID.
        If the user does not exist, provisions a new user and tenant dynamically.
        Raises ValueError if the user exists but lacks a tenant mapping.
        """
        user_id = await self.repository.get_user_id_by_email(email)

        if user_id is None:
            # JIT Provisioning
            return await self.repository.provision_tenant_for_user(email, name)

        tenant_id = await self.repository.get_tenant_id_for_user(user_id)
        if tenant_id is None:
            raise ValueError(f"User {email} exists but is not mapped to any tenant.")

        return tenant_id
