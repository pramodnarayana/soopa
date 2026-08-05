import sys

sys.path.append("core/platform/packages/orm/src")
sys.path.append("core/ucp/packages/models/src")
from platform_orm.models.core import UcpBase
from ucp_models.events import *
from ucp_models.identity import *
from ucp_models.infrastructure import *
from ucp_models.subscriptions import *
from ucp_models.webhooks import *

print(UcpBase.metadata.tables.keys())
