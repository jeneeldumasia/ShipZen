# Task 2 — PostgreSQL (Bitnami)
# Single instance, 10Gi persistence (survives pod restarts within a session).
# Destroyed cleanly with the cluster on terraform destroy.
# Writes a Kubernetes Secret "deployhub-db-credentials" with key "url"
# containing the full psycopg2-compatible connection string.
# This matches the secretKeyRef already in infra/builder/deployment.yaml
# and will be referenced by the controller, worker, and API server manifests.

locals {
  pg_database = "deployhub"
  pg_username = "deployhub"
  pg_password = "deployhub-secret-change-me"  # Overridden by var.pg_password in prod
  pg_host     = "postgres-postgresql.deployhub-system.svc.cluster.local"
  pg_port     = 5432
}

resource "helm_release" "postgresql" {
  name             = "postgres"
  repository       = "https://charts.bitnami.com/bitnami"
  chart            = "postgresql"
  version          = "15.5.23"
  namespace        = "deployhub-system"
  create_namespace = true

  set {
    name  = "auth.database"
    value = local.pg_database
  }

  set {
    name  = "auth.username"
    value = local.pg_username
  }

  set {
    name  = "auth.password"
    value = var.pg_password != "" ? var.pg_password : local.pg_password
  }

  # Disable the default postgres superuser password prompt
  set {
    name  = "auth.postgresPassword"
    value = var.pg_password != "" ? var.pg_password : local.pg_password
  }

  set {
    name  = "primary.persistence.enabled"
    value = "true"
  }

  set {
    name  = "primary.persistence.size"
    value = "10Gi"
  }

  # Single instance — no read replicas (cost)
  set {
    name  = "readReplicas.replicaCount"
    value = "0"
  }

  depends_on = [module.eks, helm_release.aws_load_balancer_controller]
}

# Write a Kubernetes Secret containing the full DATABASE_URL connection string.
# All services (worker, controller, builder, API) mount this secret as an env var.
resource "kubernetes_secret" "db_credentials" {
  metadata {
    name      = "deployhub-db-credentials"
    namespace = "deployhub-system"
  }

  data = {
    url = "postgresql://${local.pg_username}:${var.pg_password != "" ? var.pg_password : local.pg_password}@${local.pg_host}:${local.pg_port}/${local.pg_database}"
  }

  depends_on = [helm_release.postgresql]
}

# Write a Kubernetes Secret for the S3 bucket name.
# The builder mounts this to populate S3_LOG_BUCKET.
resource "kubernetes_secret" "s3_config" {
  metadata {
    name      = "deployhub-s3-config"
    namespace = "deployhub-system"
  }

  data = {
    bucket_name = aws_s3_bucket.build_logs.id
  }

  depends_on = [aws_s3_bucket.build_logs, module.eks]
}

# ECR repository URL secret — mounted by the API server to auto-generate image URIs.
# Users never see this value; the API constructs image_uri = ECR_URL:deployment_id.
resource "kubernetes_secret" "ecr_config" {
  metadata {
    name      = "deployhub-ecr-config"
    namespace = "deployhub-system"
  }

  data = {
    repository_url  = aws_ecr_repository.builds.repository_url
    # Just the hostname portion — used by the controller to render imagePullSecrets
    registry_hostname = split("/", aws_ecr_repository.builds.repository_url)[0]
  }

  depends_on = [aws_ecr_repository.builds, module.eks]
}
