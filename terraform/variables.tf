variable "aws_region" {
  description = "The AWS region to deploy the infrastructure into."
  type        = string
  default     = "us-east-1"
}

variable "pg_password" {
  description = "PostgreSQL password for the deployhub user. If empty, a default is used (not suitable for production)."
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

variable "platform_instance_type" {
  description = "The EC2 instance type for the platform node group. This should be determined dynamically to avoid Learner Lab limits."
  type        = string
  default     = "c7i-flex.large"
}
