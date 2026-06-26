import asyncio
import pytest
from bots_core.infrastructure.config.context import BotsContext, get_context, set_context
from bots_core.infrastructure.config import botsglobal

@pytest.mark.asyncio
async def test_botsglobal_proxy_isolates_state_across_tasks():
    """
    Enterprise Standard Verification:
    Ensure that the legacy `botsglobal` mutable singleton proxy
    perfectly isolates state using ContextVars when executed concurrently.
    """
    async def run_tenant_a():
        # Setup context for Tenant A
        ctx = BotsContext(ini="TenantA_Config")
        set_context(ctx)

        # Verify access through the global proxy
        assert botsglobal.ini == "TenantA_Config"

        # Yield control to let Tenant B modify the proxy
        await asyncio.sleep(0.1)

        # Verify Tenant A's state was NOT overwritten
        assert botsglobal.ini == "TenantA_Config"

    async def run_tenant_b():
        # Yield control initially to let Tenant A start
        await asyncio.sleep(0.05)

        # Setup context for Tenant B
        ctx = BotsContext(ini="TenantB_Config")
        set_context(ctx)

        # Verify access through the global proxy
        assert botsglobal.ini == "TenantB_Config"

    # Run both tenants concurrently
    await asyncio.gather(run_tenant_a(), run_tenant_b())
