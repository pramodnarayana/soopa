import structlog
from fastapi import HTTPException, Request, status
from identity.domain.identity_context import IdentityContext
from identity.domain.models.authorization import Capability

logger = structlog.get_logger(__name__)


class RequireCapability:
    """
    FastAPI dependency that enforces PBAC capability requirements.

    Usage:
        @router.get("/invoices", dependencies=[Depends(RequireCapability(Capability.INVOICES_READ))])
    """

    def __init__(self, required_capability: str):
        self.required_capability = required_capability

    def __call__(self, request: Request) -> IdentityContext:
        """
        Extracts the identity context from the request and verifies the capability.
        """
        # Attempt to get the identity context from the request state (set by auth middleware)
        identity: IdentityContext | None = getattr(request.state, "identity", None)

        if not identity:
            logger.warning("authz.denied.unauthenticated", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

        # Platform admins intrinsically have all capabilities
        if identity.is_platform_admin:
            logger.info(
                "authz.granted.platform_admin",
                path=request.url.path,
                user_id=identity.subject,
                required_capability=self.required_capability,
            )
            return identity

        # Tenant admins have all capabilities within their tenant except platform-level access
        if (
            Capability.TENANT_ADMIN.value in identity.capabilities
            and self.required_capability != Capability.PLATFORM_ADMIN.value
        ):
            logger.info(
                "authz.granted.tenant_admin",
                path=request.url.path,
                user_id=identity.subject,
                required_capability=self.required_capability,
            )
            return identity

        # Check if the required capability is in the user's resolved capabilities
        if self.required_capability not in identity.capabilities:
            logger.warning(
                "authz.denied.missing_capability",
                path=request.url.path,
                tenant_id=identity.tenant_id,
                user_id=identity.subject,
                required_capability=self.required_capability,
                actual_capabilities=list(identity.capabilities),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden. Missing required capability: {self.required_capability}",
            )

        return identity
