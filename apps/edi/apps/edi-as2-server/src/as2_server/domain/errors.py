"""
Domain and Infrastructure Exceptions for AS2 Server.
"""

from seedwork.domain.exceptions import DomainError, ErrorCode


class AmbiguousTenantRoutingError(DomainError):
    """Raised when multiple tenants or routes match an AS2 identifier or ISA pair."""

    def __init__(self, identifier: str) -> None:
        super().__init__(
            message=f"Ambiguous tenant routing match: multiple tenants match '{identifier}'",
            code=ErrorCode.CONFLICT,
        )
