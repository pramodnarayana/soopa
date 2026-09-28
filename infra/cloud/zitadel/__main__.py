import os

import pulumi
import pulumiverse_zitadel as zitadel
from dotenv import load_dotenv

# Load the root .env file as the Single Source of Truth
load_dotenv("../../.env")

config = pulumi.Config()
company_name = os.environ.get("COMPANY_NAME", "FlowWolf")
company_domain = os.environ.get("COMPANY_DOMAIN", "flowwolf.io")
ucp_project_name = os.environ.get("UCP_PROJECT_NAME", "UCP")
edi_project_name = os.environ.get("EDI_PROJECT_NAME", "EDI")
idp_project_name = os.environ.get("IDP_PROJECT_NAME", "IDP")

_env = pulumi.get_stack()

# Option 1: Local execution uses the local .env setup
if _env == "local":
    jwt_profile_file = os.environ.get("IDENTITY_JWT_PROFILE_FILE")
    jwt_profile_json = None
else:
    # Option 2: Enterprise CI/CD seamlessly fetches the secret directly into Pulumi RAM
    import pulumi_aws as aws

    # 1. We dynamically look up the ARN of the machinekey secret based on environment naming conventions
    secret_meta = aws.secretsmanager.get_secrets(
        filters=[{"name": "name", "values": [f"platform/{_env}-zitadel-machinekey"]}]
    )

    # 2. We dynamically fetch the secret payload (the actual RSA key JSON)
    secret_value = aws.secretsmanager.get_secret_version(secret_id=secret_meta.arns[0])

    # 3. We dynamically fetch the master domain from the platform stack
    platform = pulumi.StackReference(f"organization/platform/{_env}")
    zitadel_domain = platform.require_output("staging_domain")

    jwt_profile_file = None
    jwt_profile_json = secret_value.secret_string


# Explicit Provider Instance
zitadel_provider = zitadel.Provider(
    "explicit-zitadel-provider",
    domain=zitadel_domain.apply(lambda d: f"identity.{d}")
    if _env != "local"
    else os.environ.get("IDENTITY_DOMAIN", "ucp.localhost"),
    insecure=config.require_bool("insecure"),
    port=config.require("port"),
    jwt_profile_file=jwt_profile_file,
    jwt_profile_json=jwt_profile_json,
)

# Organization
platform_org = zitadel.Org(
    "platform-org", name=company_name, opts=pulumi.ResourceOptions(provider=zitadel_provider)
)

# Machine User
iam_manager_sa = zitadel.MachineUser(
    "iam-manager-sa",
    org_id=platform_org.id,
    user_name="iam-manager-sa",
    name="IAM Manager Service Account",
    description="Programmatic user for IAM Manager to manage tenants",
    access_token_type="ACCESS_TOKEN_TYPE_BEARER",  # noqa: S106 - Zitadel SDK requires explicit enum string literal for token type
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

iam_manager_sa_key = zitadel.MachineKey(
    "iam-manager-sa-key",
    org_id=platform_org.id,
    user_id=iam_manager_sa.id,
    key_type="KEY_TYPE_JSON",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# Human User
platform_admin = zitadel.HumanUser(
    "platform-admin",
    org_id=platform_org.id,
    user_name=f"platform.admin@{company_domain}",
    first_name="Platform",
    last_name="Admin",
    display_name=f"{company_name} Platform Admin",
    email=f"platform.admin@{company_domain}",
    is_email_verified=True,
    initial_password="Password1!",  # noqa: S106 - Hardcoded baseline password for local staging environment bootstrap
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# Instance Member (Instance Owner)
iam_manager_sa_instance_owner = zitadel.InstanceMember(
    "iam-manager-sa-instance-owner",
    user_id=iam_manager_sa.id,
    roles=["IAM_OWNER"],
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# UCP Project
ucp = zitadel.Project(
    "ucp",
    name=ucp_project_name,
    org_id=platform_org.id,
    project_role_assertion=True,
    project_role_check=True,
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

platform_admin_role = zitadel.ProjectRole(
    "platform-admin-role",
    org_id=platform_org.id,
    project_id=ucp.id,
    role_key="PlatformAdmin",
    display_name="Platform Administrator",
    group="Platform",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

tenant_admin_role = zitadel.ProjectRole(
    "tenant-admin-role",
    org_id=platform_org.id,
    project_id=ucp.id,
    role_key="TenantAdmin",
    display_name="Tenant Administrator",
    group="Tenant",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

tenant_user_role = zitadel.ProjectRole(
    "tenant-user-role",
    org_id=platform_org.id,
    project_id=ucp.id,
    role_key="TenantUser",
    display_name="Standard Tenant User",
    group="Tenant",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# Platform Admin Grant
platform_admin_grant = zitadel.UserGrant(
    "platform-admin-grant",
    org_id=platform_org.id,
    project_id=ucp.id,
    user_id=platform_admin.id,
    role_keys=[platform_admin_role.role_key],
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# Dynamically calculate Dashboard Redirect URIs based on the deployed environment domain
# If local, it falls back to localhost. If AWS, it uses the platform stack's domain.
if _env == "local":
    dashboard_url = "http://localhost:5173"
else:
    dashboard_url = zitadel_domain.apply(lambda d: f"https://dashboard.{d}")

redirect_uris = [
    dashboard_url.apply(lambda url: f"{url}/callback")
    if isinstance(dashboard_url, pulumi.Output)
    else f"{dashboard_url}/callback"
]
post_logout_redirect_uris = [dashboard_url]

# Applications
ucp_web_dashboard = zitadel.ApplicationOidc(
    "ucp-web-dashboard",
    org_id=platform_org.id,
    project_id=ucp.id,
    name="UCP Web Dashboard",
    redirect_uris=redirect_uris,
    post_logout_redirect_uris=post_logout_redirect_uris,
    response_types=["OIDC_RESPONSE_TYPE_CODE"],
    grant_types=["OIDC_GRANT_TYPE_AUTHORIZATION_CODE"],
    app_type="OIDC_APP_TYPE_USER_AGENT",
    auth_method_type="OIDC_AUTH_METHOD_TYPE_NONE",
    access_token_type="OIDC_TOKEN_TYPE_JWT",  # noqa: S106 - Zitadel SDK requires explicit enum string literal for token type
    access_token_role_assertion=True,
    dev_mode=_env == "local",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

ucp_api = zitadel.ApplicationApi(
    "ucp-api",
    org_id=platform_org.id,
    project_id=ucp.id,
    name="UCP API",
    auth_method_type="API_AUTH_METHOD_TYPE_PRIVATE_KEY_JWT",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# EDI Project
edi = zitadel.Project(
    "edi",
    name=edi_project_name,
    org_id=platform_org.id,
    project_role_assertion=True,
    project_role_check=False,
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

edi_api = zitadel.ApplicationApi(
    "edi-api",
    org_id=platform_org.id,
    project_id=edi.id,
    name="EDI API",
    auth_method_type="API_AUTH_METHOD_TYPE_PRIVATE_KEY_JWT",
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# IDP Project
idp = zitadel.Project(
    "idp",
    name=idp_project_name,
    org_id=platform_org.id,
    project_role_assertion=True,
    project_role_check=False,
    opts=pulumi.ResourceOptions(provider=zitadel_provider),
)

# Outputs
pulumi.export("platform_org_id", platform_org.id)
pulumi.export("ucp_project_id", ucp.id)
pulumi.export("edi_project_id", edi.id)
pulumi.export("ucp_web_client_id", ucp_web_dashboard.client_id)
pulumi.export("ucp_api_client_id", ucp_api.client_id)
pulumi.export("iam_manager_sa_key", iam_manager_sa_key.key_details)
pulumi.export("edi_api_client_id", edi_api.client_id)
pulumi.export("platform_admin_id", platform_admin.id)
