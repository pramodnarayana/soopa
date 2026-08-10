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
  default     = "Soopaidp"
}
