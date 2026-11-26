from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from identity.domain.exceptions import IdentityError, IdentityErrorCode
from identity.domain.identity_context import IdentityContext, identity_context_from_claims
from identity.ports.outbound.token_verifier_port import TokenValidationError, TokenVerifierPort

logger = structlog.get_logger(__name__)


class AuthenticationError(Exception):
    """Raised when token validation fails (e.g., expired, invalid signature)."""


class TenantNotProvisionedError(Exception):
    """Raised when a valid IdP token contains a tenant ID that is not provisioned in the system."""

    def __init__(self, tenant_id: str):
        super().__init__(
            f"Authentication failed: The organization '{tenant_id}' is not provisioned in this system."
        )
        self.tenant_id = tenant_id


@dataclass(frozen=True)
class AuthenticateCommand:
    """Command to authenticate a user via bearer token."""

    authorization_header: str | None


async def authenticate_bearer_token_result(
    command: AuthenticateCommand,
    token_verifier: TokenVerifierPort,
) -> Result[IdentityContext, IdentityError]:
    """First-class Result-returning bearer token authentication (no exceptions for expected denials)."""
    if command.authorization_header is None:
        logger.error("authentication_failed", reason="missing_header")
        return Result.fail(
            IdentityError(
                code=IdentityErrorCode.MISSING_TOKEN,
                message="Missing bearer token.",
            )
        )

    parts = command.authorization_header.split(maxsplit=1)
    if not parts or parts[0].lower() != "bearer":
        logger.error("authentication_failed", reason="missing_bearer_prefix")
        return Result.fail(
            IdentityError(
                code=IdentityErrorCode.MISSING_TOKEN,
                message="Missing bearer token.",
            )
        )

    if len(parts) == 1 or not parts[1].strip():
        logger.error("authentication_failed", reason="empty_token")
        return Result.fail(
            IdentityError(
                code=IdentityErrorCode.MISSING_TOKEN,
                message="Empty bearer token.",
            )
        )

    token = parts[1].strip()

    try:
        claims = await token_verifier.verify(token)
    except TokenValidationError as e:
        logger.error("authentication_failed", reason="invalid_token", error=str(e))
        return Result.fail(
            IdentityError(
                code=IdentityErrorCode.INVALID_TOKEN,
                message=f"Authentication failed: {e!s}",
            )
        )

    return Result.ok(identity_context_from_claims(claims))


async def authenticate_bearer_token(
    command: AuthenticateCommand,
    token_verifier: TokenVerifierPort,
) -> IdentityContext:
    res = await authenticate_bearer_token_result(command, token_verifier)
    if res.is_err:
        raise AuthenticationError(res.unwrap_err().message)
    return res.unwrap()
