import os

os.environ.setdefault(
    "ZITADEL_MACHINE_KEY",
    '{"keyId":"mock-key","key":"mock-private-key","userId":"mock-user"}',
)
os.environ.setdefault("ZITADEL_UCP_PROJECT_ID", "mock_project_id")
os.environ.setdefault("ZITADEL_PLATFORM_ORG_ID", "mock_org_id")
os.environ.setdefault("ZITADEL_API_URL", "http://mock-zitadel")
os.environ.setdefault("ZITADEL_ISSUER", "http://mock-zitadel")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
)
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
