resource "zitadel_machine_user" "ucp_backend_service" {
  org_id            = zitadel_org.platform_org.id
  user_name         = "ucp-backend-svc"
  name              = "UCP Backend Service Account"
  description       = "Programmatic user for UCP API to manage tenants"
  access_token_type = "ACCESS_TOKEN_TYPE_BEARER"
}

resource "zitadel_machine_key" "ucp_backend_machine_key" {
  org_id          = zitadel_org.platform_org.id
  user_id         = zitadel_machine_user.ucp_backend_service.id
  key_type        = "KEY_TYPE_JSON"
}

resource "random_password" "platform_admin_password" {
  length  = 16
  special = true
}

resource "zitadel_human_user" "platform_admin" {
  org_id       = zitadel_org.platform_org.id
  user_name    = "platform.admin@${var.company_domain}"
  first_name   = "Platform"
  last_name    = "Admin"
  display_name = "${var.company_name} Platform Admin"
  email        = "platform.admin@${var.company_domain}"
  is_email_verified = true
  initial_password  = random_password.platform_admin_password.result
}

resource "zitadel_user_grant" "platform_admin_grant" {
  org_id     = zitadel_org.platform_org.id
  project_id = zitadel_project.ucp.id
  user_id    = zitadel_human_user.platform_admin.id
  role_keys  = [zitadel_project_role.platform_admin.role_key]
}

resource "zitadel_instance_member" "ucp_backend_instance_owner" {
  user_id = zitadel_machine_user.ucp_backend_service.id
  roles   = ["IAM_OWNER"]
}
