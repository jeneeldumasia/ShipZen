provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}

resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true

  # Bootstrap the GitOps Application natively within the Helm chart values
  values = [
    <<-EOT
    server:
      additionalApplications:
        - name: deployhub-platform
          namespace: argocd
          project: default
          source:
            repoURL: "https://github.com/jeneeldumasia/DeployHub.git"
            targetRevision: HEAD
            path: infra
          destination:
            server: https://kubernetes.default.svc
            namespace: default
          syncPolicy:
            automated:
              prune: true
              # Fix #5.8: selfHeal: true caused ArgoCD to fight KEDA.
              # KEDA scales the builder Deployment away from replicas: 0 when
              # there are pending builds. With selfHeal enabled, ArgoCD detects
              # the replica count drift and immediately resets it back to 0,
              # preventing builders from ever running.
              # selfHeal is disabled; KEDA is the authoritative scaler for the
              # builder Deployment. All other resources remain pruned/synced.
              selfHeal: false
            syncOptions:
              # Prevent ArgoCD from managing the builder Deployment replica count.
              # The ScaledObject owns this field.
              - RespectIgnoreDifferences=true
          ignoreDifferences:
            - group: apps
              kind: Deployment
              name: deployhub-builder
              namespace: deployhub-build
              jsonPointers:
                - /spec/replicas
        - name: deployhub-gateway
          namespace: argocd
          project: default
          source:
            repoURL: "https://github.com/jeneeldumasia/DeployHub.git"
            targetRevision: HEAD
            path: gateway
          destination:
            server: https://kubernetes.default.svc
            namespace: default
          syncPolicy:
            automated:
              prune: true
              selfHeal: true
    EOT
  ]

  depends_on = [module.eks, helm_release.kube_prometheus_stack]
}
