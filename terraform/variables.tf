variable "aws_region" {
  description = "The AWS region to deploy the infrastructure into."
  type        = string
  default     = "us-east-1"
}

variable "pg_password" {
  description = "PostgreSQL password for the shipzen user. If empty, a default is used (not suitable for production)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "grafana_password" {
  description = "Grafana admin password. If empty, a default is used."
  type        = string
  default     = ""
  sensitive   = true
}

variable "redis_password" {
  description = "Redis password for authentication. Must be set for production."
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token for DNS-01 challenge (cert-manager). Must have Zone:DNS:Edit permission."
  type        = string
  sensitive   = true
}

variable "platform_instance_type" {
  description = "EC2 instance type for the platform node group"
  type        = string
  default     = "c7i-flex.large"
}
