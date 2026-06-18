provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
    }
  }
}

resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true
  depends_on = [time_sleep.wait_for_cluster_auth, helm_release.kube_prometheus_stack]
}

resource "null_resource" "argocd_apps" {
  triggers = {
    always_run = "${timestamp()}"
  }
  provisioner "local-exec" {
    command = <<EOT
      aws eks update-kubeconfig --region ${var.aws_region} --name shipzen-cluster
      cat <<EOF | kubectl apply -f -
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shipzen-platform
  namespace: argocd
spec:
  project: default
  source:
    repoURL: "https://github.com/jeneeldumasia/ShipZen.git"
    targetRevision: HEAD
    path: infra
  destination:
    server: https://kubernetes.default.svc
    namespace: shipzen-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - RespectIgnoreDifferences=true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: shipzen-builder
      namespace: shipzen-build
      jsonPointers:
        - /spec/replicas
EOF
EOT
  }
  depends_on = [
    helm_release.argocd,
    helm_release.envoy_gateway,
    helm_release.aws_load_balancer_controller,
    helm_release.external_secrets,
    helm_release.cert_manager
  ]
}
