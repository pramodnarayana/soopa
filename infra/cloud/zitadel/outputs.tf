output "platform_org_id" {
  value = zitadel_org.platform_org.id
}

output "ucp_project_id" {
  value = zitadel_project.ucp.id
}

output "edi_project_id" {
  value = zitadel_project.edi.id
}

output "ucp_web_client_id" {
  value     = zitadel_application_oidc.ucp_web_dashboard.client_id
  sensitive = true
}

output "ucp_api_client_id" {
  value     = zitadel_application_api.ucp_api.client_id
  sensitive = true
}

output "ucp_backend_machine_key" {
  value     = zitadel_machine_key.ucp_backend_machine_key.key_details
  sensitive = true
}

output "edi_api_client_id" {
  value     = zitadel_application_api.edi_api.client_id
  sensitive = true
}

output "platform_admin_id" {
  value = zitadel_human_user.platform_admin.id
}
