# ── Runtime Security (Kyverno) ────────────────────────────────────────────────
# Google-level runtime security requires admission controllers.
# Kyverno enforces policies like "No root pods" or "Images must come from ECR".

resource "helm_release" "kyverno" {
  name             = "kyverno"
  repository       = "https://kyverno.github.io/kyverno/"
  chart            = "kyverno"
  namespace        = "kyverno"
  create_namespace = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  depends_on = [time_sleep.wait_for_cluster_auth, time_sleep.wait_for_alb_webhook]
}

resource "helm_release" "kyverno_policies" {
  name             = "kyverno-policies"
  repository       = "https://kyverno.github.io/kyverno/"
  chart            = "kyverno-policies"
  namespace        = "kyverno"
  create_namespace = true

  set {
    name  = "validationFailureAction"
    value = "Enforce"
  }

  depends_on = [helm_release.kyverno]
}
