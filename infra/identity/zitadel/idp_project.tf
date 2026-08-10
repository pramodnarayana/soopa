resource "zitadel_project" "idp" {
  name                   = var.idp_project_name
  org_id                 = zitadel_org.platform_org.id
  project_role_assertion = true
  project_role_check     = false
}
