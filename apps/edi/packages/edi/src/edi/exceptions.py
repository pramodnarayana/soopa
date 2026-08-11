from fastapi import HTTPException


class TenantNotSubscribedException(HTTPException):
    """
    Raised when a tenant attempts to access the EDI application
    but does not have an active subscription or database shard mapping.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(status_code=403, detail="edi_app_not_subscribed")
