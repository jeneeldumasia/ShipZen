# Task 1 — Redis (Bitnami)
# Single master, no replicas, no persistence.
# Queue data is ephemeral — acceptable to lose on pod restart.
# Service resolves to redis-master.deployhub-system.svc.cluster.local
# which is the address hardcoded in worker/config.py and builder/main.py.

resource "helm_release" "redis" {
  name             = "redis"
  repository       = "https://charts.bitnami.com/bitnami"
  chart            = "redis"
  namespace        = "deployhub-system"
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
  # Traffic is restricted to deployhub-system namespace via NetworkPolicy.
  set {
    name  = "auth.enabled"
    value = "false"
  }

  # Ensure the master service is named "redis-master" so the DNS entry
  # redis-master.deployhub-system.svc.cluster.local resolves correctly.
  set {
    name  = "master.service.name"
    value = "redis-master"
  }

  depends_on = [module.eks]
}
