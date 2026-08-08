from edi.dependencies.auth import require_platform_admin

"""
Platform Trading Partners router package.

Handles platform-admin-scoped operations for Trading Partners (tenant_id = 0).
Requires platform admin permissions.
"""

from fastapi import APIRouter, Depends

from edi.routers.trading_partners.platform import as2_partners, as2_partnerships, settings

_PREFIX = "/api/v1/platform/trading-partners"

# Enforce require_platform_admin on all routes in this router
router = APIRouter(
    prefix=_PREFIX,
    dependencies=[Depends(require_platform_admin)],
)

router.include_router(as2_partners.router)
router.include_router(as2_partnerships.router)
router.include_router(settings.router)
