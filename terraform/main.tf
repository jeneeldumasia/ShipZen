terraform {
  cloud {
    organization = "jeneel-shipzen" # TODO: Replace with your HCP Terraform organization name
    workspaces {
      name = "shipzen-prod"          # TODO: Replace with your HCP Terraform workspace name
    }
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }

    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

provider "aws" {
  region = var.aws_region
}

# Task 5 — resolve the current AWS account ID dynamically.
# Used to build ARNs for IRSA annotations without hardcoding 123456789012.
data "aws_caller_identity" "current" {}

# ── VPC ───────────────────────────────────────────────────────────────────────
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "shipzen-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.aws_region}a", "${var.aws_region}b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true # Cost: single NAT, acceptable for student account

  # Tags required by the AWS Load Balancer Controller to discover subnets
  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }

  tags = {
    Environment                                    = "dev"
    Project                                        = "ShipZen"
    "kubernetes.io/cluster/shipzen-cluster"      = "shared"
    "karpenter.sh/discovery"                       = "ShipZen"
  }
}

# ── EKS ───────────────────────────────────────────────────────────────────────
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = "shipzen-cluster"
  cluster_version = "1.36"

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  # Base node group — platform services, ArgoCD, controller, worker
  eks_managed_node_groups = {
    platform_nodes = {
      min_size       = 1
      max_size       = 4
      desired_size   = 2
      instance_types = [var.platform_instance_type]
      ami_type       = "AL2023_x86_64_STANDARD"

      labels = {
        "shipzen.jeneeldumasia.codes/node-type" = "platform"
      }
    }
  }

  enable_cluster_creator_admin_permissions = true

  access_entries = {
    jeneel_setup = {
      kubernetes_groups = []
      principal_arn     = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/jeneel-setup"
      policy_associations = {
        admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  cluster_addons = {
    aws-ebs-csi-driver = {
      most_recent                 = true
      service_account_role_arn    = module.ebs_csi_irsa_role.iam_role_arn
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
    }
  }
}

module "ebs_csi_irsa_role" {
  source                = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version               = "~> 5.0"
  role_name             = "ShipZenEBSCSIDriver"
  attach_ebs_csi_policy = true

  oidc_providers = {
    ex = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }
}



# Kubernetes provider — authenticated via EKS token
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}

# Wait for the EKS access entry to propagate to the control plane
# before attempting to create Kubernetes resources via the provider.
resource "time_sleep" "wait_for_cluster_auth" {
  depends_on      = [module.eks]
  create_duration = "60s"
}



# ── ECR Repository ────────────────────────────────────────────────────────────
# Task 5: ECR repo for built tenant images.
# Builder pushes here; tenant pods pull from here via IRSA.
resource "aws_ecr_repository" "builds" {
  name                 = "shipzen-builds"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # Clean up on destroy — matches teardown-per-session workflow
  force_delete = true
}

# ── Builder Service Account and Namespace ──────────────────────────────────────
module "irsa_builder" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "ShipZenBuilderRole"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["shipzen-build:shipzen-builder-sa", "shipzen-system:shipzen-worker-sa", "shipzen-system:shipzen-api-sa"]
    }
  }
}

resource "aws_iam_role_policy" "builder_ecr" {
  name = "ShipZenBuilderECRPolicy"
  role = module.irsa_builder.iam_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = [
          # Push
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          # Read (required by pack/buildpacks ANALYZING phase and crane)
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          # Management / scanning
          "ecr:DescribeImageScanFindings",
          "ecr:CreateRepository",
          "ecr:DescribeRepositories"
        ],
        Resource = [aws_ecr_repository.builds.arn, "${aws_ecr_repository.builds.arn}/*"] },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
        Resource = [aws_s3_bucket.build_logs.arn, "${aws_s3_bucket.build_logs.arn}/*"] }
    ]
  })
}

resource "kubernetes_namespace" "shipzen_build" {
  depends_on = [time_sleep.wait_for_cluster_auth]
  metadata {
    name = "shipzen-build"
    labels = {
      "pod-security.kubernetes.io/enforce"         = "baseline"
      "pod-security.kubernetes.io/enforce-version" = "latest"
      "pod-security.kubernetes.io/warn"            = "baseline"
      "pod-security.kubernetes.io/warn-version"    = "latest"
      "pod-security.kubernetes.io/audit"           = "baseline"
      "pod-security.kubernetes.io/audit-version"   = "latest"
    }
  }
}

resource "kubernetes_service_account" "builder_sa" {
  metadata {
    name      = "shipzen-builder-sa"
    namespace = kubernetes_namespace.shipzen_build.metadata[0].name
    annotations = {
      "eks.amazonaws.com/role-arn" = module.irsa_builder.iam_role_arn
    }
  }
  automount_service_account_token = true
}

# Removed ecr-pull-token secret, using ESO ECRAuthorizationToken generator instead

# ── Cloudflare Origin CA Certificate ───────────────────────────────────────────
# Replaces Let's Encrypt / Cert-Manager entirely. Valid for 15 years.
resource "tls_private_key" "origin_cert" {
  algorithm = "RSA"
}

resource "tls_cert_request" "origin_cert" {
  private_key_pem = tls_private_key.origin_cert.private_key_pem

  subject {
    common_name  = "shipzen.jeneeldumasia.codes"
    organization = "ShipZen"
  }
}

resource "cloudflare_origin_ca_certificate" "origin_cert" {
  csr                = tls_cert_request.origin_cert.cert_request_pem
  hostnames          = ["*.shipzen.jeneeldumasia.codes", "shipzen.jeneeldumasia.codes"]
  request_type       = "origin-rsa"
  requested_validity = 5475 # 15 years
}

resource "aws_secretsmanager_secret" "cloudflare_origin_cert" {
  name                    = "shipzen/cloudflare-origin-cert"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "cloudflare_origin_cert" {
  secret_id     = aws_secretsmanager_secret.cloudflare_origin_cert.id
  secret_string = jsonencode({
    "cert" = cloudflare_origin_ca_certificate.origin_cert.certificate
    "key"  = tls_private_key.origin_cert.private_key_pem
  })
}

# ── S3 Bucket for Build Logs ─────────────────────────────────────────────────
resource "aws_s3_bucket" "build_logs" {
  bucket_prefix = "shipzen-build-logs-"
  force_destroy = true # Required for terraform destroy to succeed on non-empty bucket
}

# MED-10 Fix: Add S3 lifecycle rule to expire build logs after 90 days
resource "aws_s3_bucket_lifecycle_configuration" "build_logs" {
  bucket = aws_s3_bucket.build_logs.id

  rule {
    id     = "expire_old_logs"
    status = "Enabled"

    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "build_logs" {
  bucket = aws_s3_bucket.build_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ── GitHub Actions OIDC Role ──────────────────────────────────────────────────
# Task 6: scoped down from AdministratorAccess to minimum required permissions.
# Subject restricted from wildcard * to main branch only.

data "aws_iam_policy_document" "github_actions_policy" {
  # EKS — update kubeconfig and describe cluster (needed by deploy + destroy workflows)
  statement {
    sid     = "EKSAccess"
    effect  = "Allow"
    actions = ["eks:DescribeCluster", "eks:ListClusters", "eks:UpdateClusterConfig"]
    resources = [
      "arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/shipzen-cluster"
    ]
  }

  # Terraform state operations (if using S3 backend in future)
  statement {
    sid     = "TerraformEKSManage"
    effect  = "Allow"
    actions = [
      "eks:Describe*",
      "eks:Update*",
      "eks:List*",
      "ec2:Describe*",
      "iam:GetRole", "iam:CreateRole", "iam:DeleteRole",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy",
      "iam:GetRolePolicy", "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider",
      "iam:GetOpenIDConnectProvider",
      "iam:TagRole", "iam:UntagRole",
      "iam:PassRole",
    ]
    resources = ["*"]
  }

  # ECR — push/pull built images
  statement {
    sid    = "ECRAccess"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeRepositories",
      "ecr:CreateRepository",
      "ecr:DeleteRepository",
      "ecr:TagResource",
    ]
    resources = ["*"]
  }

  # S3 — build log bucket only
  statement {
    sid     = "S3BuildLogs"
    effect  = "Allow"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.build_logs.arn,
      "${aws_s3_bucket.build_logs.arn}/*"
    ]
  }
}

resource "aws_iam_policy" "github_actions" {
  name        = "ShipZenGitHubActionsPolicy"
  description = "Minimum permissions for ShipZen GitHub Actions CI/CD"
  policy      = data.aws_iam_policy_document.github_actions_policy.json
}

module "iam_github_oidc_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-github-oidc-role"
  version = "~> 5.0"

  # Task 6: restricted to main branch only — PR branches from forks cannot assume this role
  subjects = ["repo:jeneeldumasia/ShipZen:ref:refs/heads/main"]

  policies = {
    ShipZenGitHubActionsPolicy = aws_iam_policy.github_actions.arn
  }

  depends_on = [aws_iam_policy.github_actions]
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "aws_account_id" {
  description = "AWS account ID — use this to replace 123456789012 in IRSA ARN annotations"
  value       = data.aws_caller_identity.current.account_id
}

output "ecr_repository_url" {
  description = "ECR repository URL for built tenant images"
  value       = aws_ecr_repository.builds.repository_url
}

output "build_logs_bucket_name" {
  description = "S3 bucket name for build logs (random suffix, use this output not a hardcoded name)"
  value       = aws_s3_bucket.build_logs.id
}

output "cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "github_actions_role_arn" {
  description = "ARN of the GitHub Actions OIDC role — set as AWS_ROLE_ARN secret in GitHub"
  value       = module.iam_github_oidc_role.arn
}

# ── Cert-Manager ───────────────────────────────────────────────────
# Removed irsa_cert_manager and aws_route53_zone since Cloudflare is used.

# ── Karpenter ────────────────────────────────────────────────────────────────
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.31"

  cluster_name = module.eks.cluster_name

  enable_pod_identity  = false
  enable_irsa          = true
  irsa_oidc_provider_arn = module.eks.oidc_provider_arn
  create_iam_role      = true
  iam_role_name        = "ShipZenKarpenterController"
  iam_role_use_name_prefix = false
  create_node_iam_role = true
  node_iam_role_name   = "ShipZenKarpenterNodeRole"
  node_iam_role_use_name_prefix = false
  create_access_entry  = true
  
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}


