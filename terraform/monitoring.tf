# Task 4 — kube-prometheus-stack
# Installs Prometheus, Alertmanager, and Grafana.
# Persistence disabled — student account, data lost on pod restart is acceptable.
# PrometheusRule and ServiceMonitor CRDs are installed by this chart,
# which activates all resources in observability/.

resource "helm_release" "kube_prometheus_stack" {
  name             = "kube-prometheus-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  namespace        = "observability"
  create_namespace = true

  # Scan all namespaces for ServiceMonitor resources, not just observability
  set {
    name  = "prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues"
    value = "false"
  }

  set {
    name  = "prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues"
    value = "false"
  }

  set {
    name  = "prometheus.prometheusSpec.ruleSelectorNilUsesHelmValues"
    value = "false"
  }

  # Disable persistence (cost) - omitted storageSpec to default to emptyDir

  set {
    name  = "grafana.persistence.enabled"
    value = "false"
  }

  set {
    name  = "grafana.grafana\\.ini.database.type"
    value = "postgres"
  }

  set {
    name  = "grafana.grafana\\.ini.database.host"
    value = "postgres-postgresql.shipzen-system.svc.cluster.local:5432"
  }

  set {
    name  = "grafana.grafana\\.ini.database.name"
    value = "shipzen"
  }

  set {
    name  = "grafana.grafana\\.ini.database.user"
    value = "shipzen"
  }

  # Use env var for password to avoid .ini parser breaking on special characters like # or ;
  set {
    name  = "grafana.env.GF_DATABASE_PASSWORD"
    value = var.pg_password != "" ? var.pg_password : "shipzen-secret-change-me"
  }

  set {
    name  = "grafana.grafana\\.ini.database.ssl_mode"
    value = "disable"
  }

  set {
    name  = "grafana.assertNoLeakedSecrets"
    value = "false"
  }

  # Grafana admin password — change before exposing externally
  set {
    name  = "grafana.adminPassword"
    value = var.grafana_password != "" ? var.grafana_password : "shipzen-grafana"
  }

  set {
    name  = "grafana.grafana\\.ini.server.domain"
    value = "grafana-shipzen.jeneeldumasia.codes"
  }

  set {
    name  = "grafana.grafana\\.ini.server.root_url"
    value = "https://grafana-shipzen.jeneeldumasia.codes"
  }

  set {
    name  = "grafana.grafana\\.ini.security.allow_embedding"
    value = "true"
  }

  set {
    name  = "grafana.grafana\\.ini.auth\\.anonymous.enabled"
    value = "true"
  }

  set {
    name  = "grafana.grafana\\.ini.auth\\.anonymous.org_role"
    value = "Viewer"
  }

  # Enable the Grafana sidecar to pick up ConfigMap-based dashboards
  # (observability/dashboards/grafana-dashboards.yaml uses label grafana_dashboard: "1")
  set {
    name  = "grafana.sidecar.dashboards.enabled"
    value = "true"
  }

  set {
    name  = "grafana.sidecar.dashboards.searchNamespace"
    value = "ALL"
  }

  # Enable nodeExporter. Exception added via Kyverno PolicyException.
  set {
    name  = "nodeExporter.enabled"
    value = "true"
  }

  timeout = 900
  depends_on = [time_sleep.wait_for_cluster_auth, time_sleep.wait_for_alb_webhook, helm_release.postgresql]
}
