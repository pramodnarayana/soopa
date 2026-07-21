terraform {
  required_providers {
    zitadel = {
      source  = "zitadel/zitadel"
      version = "~> 2.0"
    }
  }
}

provider "zitadel" {
  domain           = "ucp.localhost"
  insecure         = true
  port             = "8080"
  jwt_profile_file = "machinekey.json"
}
