"""
Domain Exceptions for AS2 Server.
"""


class As2DomainError(Exception):
    """Base domain exception for AS2 server."""


class AmbiguousTenantRoutingError(As2DomainError):
    """Raised when multiple tenants or routes match an AS2 identifier or ISA pair."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Ambiguous tenant routing match: multiple tenants match '{identifier}'")
