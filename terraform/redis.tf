# Task 1 — Redis (Bitnami)
# Single master, no replicas, no persistence.
# Queue data is ephemeral — acceptable to lose on pod restart.
# Service resolves to redis-master.shipzen-system.svc.cluster.local
# which is the address hardcoded in worker/config.py and builder/main.py.

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
    name  = "auth.password"
    value = var.redis_password
  }

  # Ensure the master service is named "redis-master" so the DNS entry
  # redis-master.shipzen-system.svc.cluster.local resolves correctly.
  set {
    name  = "master.service.name"
    value = "redis-master"
  }

  depends_on = [time_sleep.wait_for_cluster_auth, helm_release.kyverno]
}
