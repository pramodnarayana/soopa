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
  description = "The domain of the Zitadel instance"
  type        = string
  default     = "ucp.localhost"
}

variable "zitadel_port" {
  description = "The port of the Zitadel instance"
  type        = string
  default     = "8080"
}

variable "zitadel_insecure" {
  description = "Whether to use an insecure connection to Zitadel"
  type        = bool
  default     = true
}

variable "ucp_web_dashboard_redirect_uris" {
  description = "Redirect URIs for the UCP Web Dashboard"
  type        = list(string)
  default     = ["http://localhost:5173/auth/callback", "http://localhost:5173/callback"]
}

variable "ucp_web_dashboard_post_logout_redirect_uris" {
  description = "Post logout redirect URIs for the UCP Web Dashboard"
  type        = list(string)
  default     = ["http://localhost:5173", "http://localhost:5173/"]
}

variable "dev_mode" {
  description = "Enable dev mode for Zitadel applications"
  type        = bool
  default     = true
}
