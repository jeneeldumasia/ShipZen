# Task 3 — Cluster Operators
# KEDA, External Secrets Operator, AWS Load Balancer Controller
# All depend on EKS being ready.

# ── KEDA ────────────────────────────────────────────────────────────────────
resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = "2.14.2"
  namespace        = "keda"
  create_namespace = true

  depends_on = [module.eks]
}

# ── External Secrets Operator ────────────────────────────────────────────────
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = "0.9.20"
  namespace        = "external-secrets"
  create_namespace = true

  depends_on = [module.eks]
}

# ── AWS Load Balancer Controller ─────────────────────────────────────────────
# Required for the Gateway's NLB annotations to provision an AWS NLB.
# Needs an IRSA role with ELB and EC2 describe permissions.

data "aws_iam_policy_document" "alb_controller" {
  statement {
    sid    = "ELBFullAccess"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:*",
      "ec2:Describe*",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:CreateSecurityGroup",
      "ec2:DeleteSecurityGroup",
      "ec2:CreateTags",
      "ec2:DeleteTags",
      "cognito-idp:DescribeUserPoolClient",
      "acm:ListCertificates",
      "acm:DescribeCertificate",
      "iam:ListServerCertificates",
      "iam:GetServerCertificate",
      "waf-regional:GetWebACL",
      "waf-regional:GetWebACLForResource",
      "waf-regional:AssociateWebACL",
      "waf-regional:DisassociateWebACL",
      "wafv2:GetWebACL",
      "wafv2:GetWebACLForResource",
      "wafv2:AssociateWebACL",
      "wafv2:DisassociateWebACL",
      "shield:GetSubscriptionState",
      "shield:DescribeProtection",
      "shield:CreateProtection",
      "shield:DeleteProtection"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "alb_controller" {
  name        = "DeployHubALBControllerPolicy"
  description = "IAM policy for the AWS Load Balancer Controller in DeployHub"
  policy      = data.aws_iam_policy_document.alb_controller.json
}

module "irsa_alb_controller" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "DeployHubALBController"

  attach_load_balancer_controller_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = "1.8.1"
  namespace  = "kube-system"

  set {
    name  = "clusterName"
    value = module.eks.cluster_name
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = module.irsa_alb_controller.iam_role_arn
  }

  depends_on = [module.eks, module.irsa_alb_controller]
}

# ── ClusterSecretStore (ESO) ──────────────────────────────────────────────────
# Task 19 / fix #5.9 + Task 18 / fix #4.1:
# Manages the ClusterSecretStore via Terraform so the AWS region and account ID
# are injected from Terraform variables rather than hardcoded in YAML.
# This replaces the static infra/secrets/cluster-secret-store.yaml for the
# ClusterSecretStore object (the ServiceAccount is still managed by ArgoCD
# but its annotation ARN is overridden here).

resource "kubernetes_manifest" "eso_service_account" {
  manifest = {
    apiVersion = "v1"
    kind       = "ServiceAccount"
    metadata = {
      name      = "external-secrets-sa"
      namespace = "external-secrets"
      annotations = {
        # Fix #4.1 + #5.9: account ID from data source, not hardcoded
        "eks.amazonaws.com/role-arn" = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/DeployHubESO"
      }
    }
  }

  depends_on = [helm_release.external_secrets]
}

resource "kubernetes_manifest" "cluster_secret_store" {
  manifest = {
    apiVersion = "external-secrets.io/v1beta1"
    kind       = "ClusterSecretStore"
    metadata = {
      name = "aws-secrets-manager"
    }
    spec = {
      provider = {
        aws = {
          service = "SecretsManager"
          # Fix #5.9: region from Terraform variable, not hardcoded
          region = var.aws_region
          auth = {
            jwt = {
              serviceAccountRef = {
                name      = "external-secrets-sa"
                namespace = "external-secrets"
              }
            }
          }
        }
      }
    }
  }

  depends_on = [kubernetes_manifest.eso_service_account]
}

# ── Cert Manager ─────────────────────────────────────────────────────────────
resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = "v1.15.1"
  namespace        = "cert-manager"
  create_namespace = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = module.irsa_cert_manager.iam_role_arn
  }

  depends_on = [module.eks]
}

# ── Karpenter ────────────────────────────────────────────────────────────────
resource "helm_release" "karpenter" {
  name             = "karpenter"
  repository       = "oci://public.ecr.aws/karpenter"
  chart            = "karpenter"
  version          = "0.37.0"
  namespace        = "karpenter"
  create_namespace = true

  set {
    name  = "settings.clusterName"
    value = module.eks.cluster_name
  }

  set {
    name  = "settings.interruptionQueue"
    value = module.karpenter.queue_name
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = module.karpenter.iam_role_arn
  }

  depends_on = [module.eks]
}
