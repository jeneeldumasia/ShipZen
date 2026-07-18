# Task 1 — Redis (Bitnami)
# Single master, no replicas, no persistence.
# Queue data is ephemeral — acceptable to lose on pod restart.
# Service resolves to redis-master.shipzen-system.svc.cluster.local
# which is the address hardcoded in worker/config.py and builder/main.py.

resource "random_password" "redis_password" {
  length  = 32
  special = false
}

locals {
  redis_password = var.redis_password != "" ? var.redis_password : random_password.redis_password.result
}

resource "aws_secretsmanager_secret" "redis_password" {
  name                    = "shipzen/redis-password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "redis_password" {
  secret_id     = aws_secretsmanager_secret.redis_password.id
  secret_string = local.redis_password
}

resource "null_resource" "apply_redis_external_secret" {
  triggers = {
    version = aws_secretsmanager_secret_version.redis_password.version_id
  }
  provisioner "local-exec" {
    command = <<EOT
      kubectl create namespace shipzen-system --dry-run=client -o yaml | kubectl apply -f -
      cat <<EOF | aws eks update-kubeconfig --region ${var.aws_region} --name shipzen-cluster && kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: redis-auth
  namespace: shipzen-system
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: redis-auth
  data:
    - secretKey: redis-password
      remoteRef:
        key: shipzen/redis-password
EOF
EOT
  }
  depends_on = [null_resource.apply_cluster_secret_store]
}

resource "helm_release" "redis" {
  name             = "redis"
  repository       = "oci://registry-1.docker.io/bitnamicharts"
  chart            = "redis"
  version          = "27.0.8"
  namespace        = "shipzen-system"
  create_namespace = true

  set {
    name  = "architecture"
    value = "standalone"
  }

  # Disable persistence — queue is ephemeral
  set {
    name  = "master.persistence.enabled"
    value = "false"
  }

  # Disable auth for simplicity inside the private cluster network.
  # Traffic is restricted to shipzen-system namespace via NetworkPolicy.
  set {
    name  = "auth.enabled"
    value = "true"
  }
  set {
    name  = "auth.existingSecret"
    value = "redis-auth"
  }
  set {
    name  = "auth.existingSecretPasswordKey"
    value = "redis-password"
  }

  # Ensure the master service is named "redis-master" so the DNS entry
  # redis-master.shipzen-system.svc.cluster.local resolves correctly.
  set {
    name  = "master.service.name"
    value = "redis-master"
  }

  depends_on = [time_sleep.wait_for_cluster_auth, helm_release.kyverno, null_resource.apply_redis_external_secret]
}
