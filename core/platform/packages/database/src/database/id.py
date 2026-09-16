# This module has been removed.
# ID prefixes are now defined as class-level constants on each entity
# within its respective bounded context (DDD: constants live with their domain).
#
# Examples:
#   from database.models.identity import Tenant
#   from ucp_models.subscriptions import App
#
#   tenant_id = generate_id(Tenant.ID_PREFIX)
#   app_id    = generate_id(App.ID_PREFIX)
