# This module has been removed.
# ID prefixes are now defined as class-level constants on each entity
# within its respective bounded context (DDD: constants live with their domain).
#
# Examples:
#   from ucp_models.identity import Tenant
#   from ucp_models.subscriptions import App
#
#   tenant_id = f"{Tenant.ID_PREFIX}_{os.urandom(12).hex()}"
#   app_id    = f"{App.ID_PREFIX}_{os.urandom(12).hex()}"
