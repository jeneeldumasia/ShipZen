locals {
  pg_database = "deployhub"
  pg_username = "deployhub"
  pg_password = "deployhub-secret-change-me"  # Overridden by var.pg_password in prod
  pg_host     = "postgres-postgresql.deployhub-system.svc.cluster.local"
  pg_port     = 5432
}

# Wait for the EBS CSI controller pod to be running before trying to create PVCs.
# The addon is registered in module.eks but the controller pod takes ~30s to
# reach Running state after the addon API call returns.
resource "time_sleep" "wait_for_ebs_csi" {
  create_duration = "45s"
  depends_on      = [module.eks]
}

resource "helm_release" "postgresql" {
  name             = "postgres"
  repository       = "https://charts.bitnami.com/bitnami"
  chart            = "postgresql"
  namespace        = "deployhub-system"
  create_namespace = true

  # Fix: explicitly set gp2 StorageClass.
  # Without this, the PVC uses the cluster default which on EKS 1.36 + AL2023
  # may not provision correctly. gp2 is always available via the EBS CSI addon
  # declared in main.tf and is the safest universal choice.
  set {
    name  = "primary.persistence.storageClass"
    value = "gp2"
  }

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

  # The EBS CSI driver mounts volumes as root (UID 0).
  # The postgres user (UID 1001) gets Permission Denied during initdb without
  # this initContainer that chowns the volume to 1001 before postgres starts.
  set {
    name  = "volumePermissions.enabled"
    value = "true"
  }

  # 15 min: Karpenter node provision (~3 min) + EBS attach (~1 min) + DB init (~2 min)
  # Previous 10 min timeout was too tight on a cold cluster boot.
  timeout = 900

  # Fix: removed depends_on [helm_release.keda, helm_release.karpenter].
  # Postgres does not depend on KEDA or Karpenter — it runs on the managed
  # node group. The real dependency is the EBS CSI addon being ready.
  depends_on = [time_sleep.wait_for_ebs_csi]
}

# Full DATABASE_URL connection string — all services mount this as an env var.
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

# S3 bucket name for build logs — mounted by builder as S3_LOG_BUCKET.
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

# ECR repo URL — mounted by API server and controller.
# API: builds image_uri = ECR_URL:deployment_id (user never sees this)
# Controller: passes ECR_REGISTRY to tenant namespace template for imagePullSecrets
resource "kubernetes_secret" "ecr_config" {
  metadata {
    name      = "deployhub-ecr-config"
    namespace = "deployhub-system"
  }

  data = {
    repository_url    = aws_ecr_repository.builds.repository_url
    registry_hostname = split("/", aws_ecr_repository.builds.repository_url)[0]
  }

  depends_on = [aws_ecr_repository.builds, module.eks]
}
