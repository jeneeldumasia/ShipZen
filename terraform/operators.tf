# Task 3 — Cluster Operators
# KEDA, External Secrets Operator, AWS Load Balancer Controller
# All depend on EKS being ready.

# ── KEDA ────────────────────────────────────────────────────────────────────
resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  namespace        = "keda"
  create_namespace = true

  depends_on = [module.eks, helm_release.external_secrets]
}

# ── External Secrets Operator ────────────────────────────────────────────────
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "external-secrets-sa"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/DeployHubESO"
  }

  depends_on = [module.eks, helm_release.cert_manager]
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

resource "time_sleep" "wait_for_eso_crds" {
  depends_on      = [helm_release.external_secrets]
  create_duration = "60s"
}



resource "null_resource" "cluster_secret_store" {
  triggers = {
    always_run = "${timestamp()}"
  }
  provisioner "local-exec" {
    command = <<EOT
      aws eks update-kubeconfig --region ${var.aws_region} --name deployhub-cluster
      
      echo "Waiting for ClusterSecretStore CRD to be registered..."
      until kubectl get crd clustersecretstores.external-secrets.io >/dev/null 2>&1; do
        echo "Waiting for CRD..."
        sleep 5
      done
      kubectl wait --for condition=established --timeout=120s crd/clustersecretstores.external-secrets.io

      echo "Refreshing Kubernetes API discovery cache..."
      rm -rf ~/.kube/cache
      kubectl api-resources > /dev/null || true

      cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: "${var.aws_region}"
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets-sa
            namespace: external-secrets
EOF
EOT
  }
  depends_on = [time_sleep.wait_for_eso_crds]
}

# ── Cert Manager ─────────────────────────────────────────────────────────────
resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  namespace        = "cert-manager"
  create_namespace = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  depends_on = [module.eks, helm_release.karpenter]
}

# ── Karpenter ────────────────────────────────────────────────────────────────
resource "helm_release" "karpenter" {
  name             = "karpenter"
  repository       = "oci://public.ecr.aws/karpenter"
  chart            = "karpenter"
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

  depends_on = [module.eks, helm_release.aws_load_balancer_controller]
}
