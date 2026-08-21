# ID generation has been removed from this module.
#
# ID prefixes are now class-level constants on each entity model, e.g.:
#   Tenant.ID_PREFIX    => "ten"
#   User.ID_PREFIX      => "usr"
#   App.ID_PREFIX       => "app"
#
# To generate a prefixed ID, use the entity constant directly:
#   import os
#   tenant_id = f"{Tenant.ID_PREFIX}_{os.urandom(12).hex()}"
