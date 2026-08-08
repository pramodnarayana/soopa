"""
Shell-level Authentication Middleware.

The authentication middleware for the unified Shell validates the Bearer token
once at the public entrypoint and populates ``request.state.identity``.

Architecture note:
  - The UCP package defines its own authentication middleware for standalone
    deployment scenarios. In the Modular Monolith, however, this middleware
    must live on the Shell so it intercepts ALL requests — both UCP-handled
    routes (inlined on Shell) and EDI-handled routes (EDI sub-app mount).
  - This module re-exports the UCP auth middleware implementation by reference.
    No logic is duplicated. The auth algorithm (JWKS verification, token
    parsing) lives in the identity package and is domain-agnostic.
  - The EDI domain authenticates at the dependency level (per-route guards).
    This middleware adds a complementary perimeter check that populates
    ``request.state.identity`` for both domains.
"""

from ucp.adapters.inbound.http.middleware.authentication import AuthenticationMiddleware
from ucp.adapters.inbound.http.middleware.tenant_context import TenantContextMiddleware

__all__ = ["AuthenticationMiddleware", "TenantContextMiddleware"]
