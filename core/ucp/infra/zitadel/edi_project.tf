resource "zitadel_project" "edi" {
  name                   = var.edi_project_name
  org_id                 = zitadel_org.platform_org.id
  project_role_assertion = true
  project_role_check     = false
}

resource "zitadel_application_api" "edi_api" {
  org_id           = zitadel_org.platform_org.id
  project_id       = zitadel_project.edi.id
  name             = "EDI API"
  auth_method_type = "API_AUTH_METHOD_TYPE_PRIVATE_KEY_JWT"
}
