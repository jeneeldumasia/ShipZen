terraform {
  cloud {
    organization = "jeneel-deployhub" # TODO: Replace with your HCP Terraform organization name
    workspaces {
      name = "deployhub-prod"          # TODO: Replace with your HCP Terraform workspace name
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
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.14.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
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

  name = "deployhub-vpc"
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
    Project                                        = "DeployHub"
    "kubernetes.io/cluster/deployhub-cluster"      = "shared"
    "karpenter.sh/discovery"                       = "DeployHub"
  }
}

# ── EKS ───────────────────────────────────────────────────────────────────────
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = "deployhub-cluster"
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
        "deployhub.jeneeldumasia.codes/node-type" = "platform"
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
    github_actions = {
      kubernetes_groups = []
      principal_arn     = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/DeployHub-AA-SuperRole"
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
  role_name             = "DeployHubEBSCSIDriver"
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
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  load_config_file       = false
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

# ── ECR Repository ────────────────────────────────────────────────────────────
# Task 5: ECR repo for built tenant images.
# Builder pushes here; tenant pods pull from here via IRSA.
resource "aws_ecr_repository" "builds" {
  name                 = "deployhub-builds"
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

  role_name = "DeployHubBuilderRole"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["deployhub-build:deployhub-builder-sa"]
    }
  }
}

resource "aws_iam_role_policy" "builder_ecr" {
  name = "DeployHubBuilderECRPolicy"
  role = module.irsa_builder.iam_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability","ecr:PutImage",
        "ecr:InitiateLayerUpload","ecr:UploadLayerPart","ecr:CompleteLayerUpload",
        "ecr:DescribeImageScanFindings", "ecr:CreateRepository", "ecr:DescribeRepositories"],
        Resource = [aws_ecr_repository.builds.arn, "${aws_ecr_repository.builds.arn}/*"] }
    ]
  })
}

resource "kubernetes_namespace" "deployhub_build" {
  metadata {
    name = "deployhub-build"
    labels = {
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "latest"
      "pod-security.kubernetes.io/audit"           = "restricted"
      "pod-security.kubernetes.io/audit-version"   = "latest"
      "pod-security.kubernetes.io/warn"            = "restricted"
      "pod-security.kubernetes.io/warn-version"    = "latest"
    }
  }
}

resource "kubernetes_service_account" "builder_sa" {
  metadata {
    name      = "deployhub-builder-sa"
    namespace = kubernetes_namespace.deployhub_build.metadata[0].name
    annotations = {
      "eks.amazonaws.com/role-arn" = module.irsa_builder.iam_role_arn
    }
  }
  automount_service_account_token = false
}

# Removed ecr-pull-token secret, using ESO ECRAuthorizationToken generator instead

# ── Cloudflare API Token Secret ───────────────────────────────────────────────
# Used by External Secrets Operator to inject Cloudflare credentials for Cert-Manager
resource "aws_secretsmanager_secret" "cloudflare_api_token" {
  name                    = "deployhub/cloudflare-api-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "cloudflare_api_token" {
  secret_id     = aws_secretsmanager_secret.cloudflare_api_token.id
  secret_string = jsonencode({ "api-token" = var.cloudflare_api_token })
}

# ── S3 Bucket for Build Logs ─────────────────────────────────────────────────
resource "aws_s3_bucket" "build_logs" {
  bucket_prefix = "deployhub-build-logs-"
  force_destroy = true # Required for terraform destroy to succeed on non-empty bucket
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
      "arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/deployhub-cluster"
    ]
  }

  # Terraform state operations (if using S3 backend in future)
  statement {
    sid     = "TerraformEKSManage"
    effect  = "Allow"
    actions = [
      "eks:*",
      "ec2:*",
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
  name        = "DeployHubGitHubActionsPolicy"
  description = "Minimum permissions for DeployHub GitHub Actions CI/CD"
  policy      = data.aws_iam_policy_document.github_actions_policy.json
}

module "iam_github_oidc_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-github-oidc-role"
  version = "~> 5.0"

  # Task 6: restricted to main branch only — PR branches from forks cannot assume this role
  subjects = ["repo:jeneeldumasia/DeployHub:ref:refs/heads/main"]

  policies = {
    DeployHubGitHubActionsPolicy = aws_iam_policy.github_actions.arn
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
  iam_role_name        = "DeployHubKarpenterController"
  create_node_iam_role = true
  node_iam_role_name   = "DeployHubKarpenterNodeRole"
  create_access_entry  = true
  
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

data "cloudflare_zone" "deployhub" {
  name = "deployhub.jeneeldumasia.codes"
}

data "kubernetes_service" "gateway" {
  metadata {
    name      = "envoy-deployhub-system-deployhub-gateway"
    namespace = "envoy-gateway-system"
  }
}

resource "cloudflare_record" "wildcard" {
  zone_id = data.cloudflare_zone.deployhub.id
  name    = "*"
  value   = data.kubernetes_service.gateway.status[0].load_balancer[0].ingress[0].hostname
  type    = "CNAME"
  proxied = false
}
