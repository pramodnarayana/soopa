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

output "ucp_backend_pat_token" {
  value     = zitadel_personal_access_token.ucp_backend_pat.token
  sensitive = true
}
