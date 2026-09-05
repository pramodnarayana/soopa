variable "company_name" {
  description = "The name of the root organization/company"
  type        = string
  default     = "Soopa"
}

variable "company_domain" {
  description = "The main domain of the company"
  type        = string
  default     = "soopa.local"
}

variable "ucp_project_name" {
  description = "Name of the UCP Project"
  type        = string
  default     = "Soopaucp"
}

variable "edi_project_name" {
  description = "Name of the EDI Project"
  type        = string
  default     = "Soopaedi"
}

variable "idp_project_name" {
  description = "Name of the IDP Project"
  type        = string
}

variable "zitadel_domain" {
  description = "The non-localhost domain of the cloud Zitadel instance"
  type        = string
}

variable "zitadel_port" {
  description = "The TLS port of the cloud Zitadel instance"
  type        = string
}

variable "zitadel_insecure" {
  description = "Whether to disable TLS for the Zitadel provider"
  type        = bool
}

variable "ucp_web_dashboard_redirect_uris" {
  description = "HTTPS redirect URIs for the cloud UCP Web Dashboard"
  type        = list(string)
}

variable "ucp_web_dashboard_post_logout_redirect_uris" {
  description = "HTTPS post-logout redirect URIs for the cloud UCP Web Dashboard"
  type        = list(string)
}

variable "dev_mode" {
  description = "Enable dev mode for Zitadel applications"
  type        = bool
}
