# ── Runtime Security (Kyverno) ────────────────────────────────────────────────
# Google-level runtime security requires admission controllers.
# Kyverno enforces policies like "No root pods" or "Images must come from ECR".

resource "helm_release" "kyverno" {
  name             = "kyverno"
  repository       = "https://kyverno.github.io/kyverno/"
  chart            = "kyverno"
  version          = "3.2.6"
  namespace        = "kyverno"
  create_namespace = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  depends_on = [module.eks]
}

resource "helm_release" "kyverno_policies" {
  name             = "kyverno-policies"
  repository       = "https://kyverno.github.io/kyverno/"
  chart            = "kyverno-policies"
  version          = "3.2.6"
  namespace        = "kyverno"
  create_namespace = true

  set {
    name  = "validationFailureAction"
    value = "Audit"
  }

  depends_on = [helm_release.kyverno]
}
