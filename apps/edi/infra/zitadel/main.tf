terraform {
  required_providers {
    zitadel = {
      source  = "zitadel/zitadel"
    }
  }
}

provider "zitadel" {
  domain           = "localhost"
  insecure         = true
  port             = "8080"
  jwt_profile_file = "machinekey.json"
}

# 1. Create the SOOPA Organization
resource "zitadel_org" "soopa" {
  name = "SOOPA"
}

# 2. Create Projects inside SOOPA
resource "zitadel_project" "edi" {
  name                     = "Soopa EDI"
  org_id                   = zitadel_org.soopa.id
  project_role_assertion   = true
  project_role_check       = false
}

resource "zitadel_project" "ip" {
  name                     = "Soopa Integration Platform"
  org_id                   = zitadel_org.soopa.id
  project_role_assertion   = true
  project_role_check       = false
}

resource "zitadel_project" "idp" {
  name                     = "Soopa Intelligent Document Processing"
  org_id                   = zitadel_org.soopa.id
  project_role_assertion   = true
  project_role_check       = false
}

# 3. Create the EDI Web App Application
resource "zitadel_application_oidc" "edi_web_app" {
  org_id                      = zitadel_org.soopa.id
  project_id                  = zitadel_project.edi.id
  name                        = "Soopa EDI Web App"
  redirect_uris               = ["http://localhost:5173/auth/callback", "http://localhost:5173/callback"]
  post_logout_redirect_uris   = ["http://localhost:5173", "http://localhost:5173/"]
  response_types              = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                 = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE"]
  app_type                    = "OIDC_APP_TYPE_USER_AGENT"
  auth_method_type            = "OIDC_AUTH_METHOD_TYPE_NONE"
  dev_mode                    = true
}

# 4. Create the API Testing Machine User
resource "zitadel_machine_user" "api_test" {
  org_id            = zitadel_org.soopa.id
  user_name         = "api-test"
  name              = "API Test User"
  description       = "Integration testing user"
  access_token_type = "ACCESS_TOKEN_TYPE_BEARER"
}

# 5. Generate PAT for the Machine User
resource "zitadel_personal_access_token" "api_test_pat" {
  org_id          = zitadel_org.soopa.id
  user_id         = zitadel_machine_user.api_test.id
}

# Outputs
output "soopa_org_id" {
  value = zitadel_org.soopa.id
}

output "edi_spa_client_id" {
  value = zitadel_application_oidc.edi_web_app.client_id
  sensitive = true
}

output "api_test_pat_token" {
  value     = zitadel_personal_access_token.api_test_pat.token
  sensitive = true
}

# ==============================================================================
# TENANT 1 (Customer: Acme Corp)
# ==============================================================================

# 1. Create the Acme Corp Organization
resource "zitadel_org" "acme" {
  name = "Acme Corp"
}

# 2. Create an API Testing Machine User for Acme Corp
resource "zitadel_machine_user" "acme_test" {
  org_id      = zitadel_org.acme.id
  user_name   = "acme-test"
  name        = "Acme Test User"
  description = "Integration testing user for Tenant 1"
  with_secret = false
  access_token_type = "ACCESS_TOKEN_TYPE_BEARER"
}

# 3. Generate a Personal Access Token (PAT) for the Acme Test User
resource "zitadel_personal_access_token" "acme_test_pat" {
  org_id  = zitadel_org.acme.id
  user_id = zitadel_machine_user.acme_test.id
}



output "acme_org_id" {
  value = zitadel_org.acme.id
}

output "acme_test_pat_token" {
  value     = zitadel_personal_access_token.acme_test_pat.token
  sensitive = true
}
