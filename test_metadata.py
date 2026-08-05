import sys

sys.path.append("core/platform/packages/orm/src")
sys.path.append("core/ucp/packages/models/src")
from platform_orm.models.core import UcpBase

# Import modules for metadata registration side effects
import ucp_models.events  # noqa: F401
import ucp_models.identity  # noqa: F401
import ucp_models.infrastructure  # noqa: F401
import ucp_models.notifications  # noqa: F401
import ucp_models.subscriptions  # noqa: F401
import ucp_models.webhooks  # noqa: F401

print(UcpBase.metadata.tables.keys())
