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

  # Disable persistence (cost)
  set {
    name  = "prometheus.prometheusSpec.storageSpec"
    value = ""
  }

  set {
    name  = "grafana.persistence.enabled"
    value = "false"
  }

  # Grafana admin password — change before exposing externally
  set {
    name  = "grafana.adminPassword"
    value = var.grafana_password != "" ? var.grafana_password : "deployhub-grafana"
  }

  set {
    name  = "grafana.grafana\\.ini.server.domain"
    value = "grafana.deployhub.jeneeldumasia.codes"
  }

  set {
    name  = "grafana.grafana\\.ini.server.root_url"
    value = "https://grafana.deployhub.jeneeldumasia.codes"
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

  depends_on = [module.eks]
}
