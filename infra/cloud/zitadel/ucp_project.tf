resource "zitadel_project" "ucp" {
  name                   = var.ucp_project_name
  org_id                 = zitadel_org.platform_org.id
  project_role_assertion = true
  project_role_check     = true
}

resource "zitadel_project_role" "platform_admin" {
  org_id       = zitadel_org.platform_org.id
  project_id   = zitadel_project.ucp.id
  role_key     = "PlatformAdmin"
  display_name = "Platform Administrator"
  group        = "Platform"
}

resource "zitadel_project_role" "tenant_admin" {
  org_id       = zitadel_org.platform_org.id
  project_id   = zitadel_project.ucp.id
  role_key     = "TenantAdmin"
  display_name = "Tenant Administrator"
  group        = "Tenant"
}

resource "zitadel_project_role" "tenant_user" {
  org_id       = zitadel_org.platform_org.id
  project_id   = zitadel_project.ucp.id
  role_key     = "TenantUser"
  display_name = "Standard Tenant User"
  group        = "Tenant"
}

resource "zitadel_application_oidc" "ucp_web_dashboard" {
  org_id                    = zitadel_org.platform_org.id
  project_id                = zitadel_project.ucp.id
  name                      = "UCP Web Dashboard"
  redirect_uris             = var.ucp_web_dashboard_redirect_uris
  post_logout_redirect_uris = var.ucp_web_dashboard_post_logout_redirect_uris
  response_types            = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types               = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE"]
  app_type                  = "OIDC_APP_TYPE_USER_AGENT"
  auth_method_type          = "OIDC_AUTH_METHOD_TYPE_NONE"
  access_token_type         = "OIDC_TOKEN_TYPE_JWT"
  access_token_role_assertion = true
  dev_mode                  = var.dev_mode
}

resource "zitadel_application_api" "ucp_api" {
  org_id           = zitadel_org.platform_org.id
  project_id       = zitadel_project.ucp.id
  name             = "UCP API"
  auth_method_type = "API_AUTH_METHOD_TYPE_PRIVATE_KEY_JWT"
}
