variable "project_id" {
  description = "Existing Google Cloud project for the development environment."
  type        = string
}

variable "region" {
  description = "European region for every new RoleCallAI data-processing resource."
  type        = string
  default     = "europe-west4"

  validation {
    condition     = startswith(var.region, "europe-")
    error_message = "RoleCallAI data processing must remain in a European region."
  }
}

variable "zone" {
  type    = string
  default = "europe-west4-a"
}

variable "summary_model_location" {
  description = "EU multi-region endpoint for Gemini summary and evaluation inference."
  type        = string
  default     = "eu"

  validation {
    condition     = var.summary_model_location == "eu"
    error_message = "Summary inference must use the Vertex AI eu multi-region endpoint."
  }
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "firestore_database" {
  type    = string
  default = "rolecall-dev"

  validation {
    condition     = var.firestore_database == "rolecall-dev" && var.firestore_database != "(default)"
    error_message = "This stack may only target the named rolecall-dev database."
  }
}

variable "image_tag" {
  description = "Manual Cloud Build tag to deploy after approval."
  type        = string
  default     = "manual"
}

variable "acme_email" {
  description = "Email for Let's Encrypt registration; replace the placeholder before apply."
  type        = string
  default     = "replace-before-apply@example.com"
}

variable "livekit_chart_version" {
  type    = string
  default = "1.9.0"
}

variable "livekit_server_version" {
  description = "Pinned LiveKit Server image version; newer clients require the v1 signaling path."
  type        = string
  default     = "1.13.5"
}

variable "cert_manager_chart_version" {
  type    = string
  default = "v1.18.2"
}

variable "ingress_nginx_chart_version" {
  type    = string
  default = "4.13.0"
}

variable "notification_email" {
  description = "Optional email channel for development alerts."
  type        = string
  default     = ""
}

variable "control_min_instances" {
  type    = number
  default = 0
}

variable "worker_min_replicas" {
  type    = number
  default = 2
}

variable "worker_max_replicas" {
  type    = number
  default = 6
}

variable "media_min_nodes" {
  type    = number
  default = 1
}

variable "media_max_nodes" {
  type    = number
  default = 3
}

variable "worker_min_nodes" {
  type    = number
  default = 2
}

variable "worker_max_nodes" {
  type    = number
  default = 6
}

variable "retention_days" {
  type    = number
  default = 90
}

variable "labels" {
  type = map(string)
  default = {
    application = "rolecallai"
    environment = "dev"
    managed-by  = "terraform"
  }
}

check "approval_inputs" {
  assert {
    condition     = var.acme_email != "replace-before-apply@example.com"
    error_message = "Set a monitored ACME email before terraform apply. Planning is still safe."
  }
}
