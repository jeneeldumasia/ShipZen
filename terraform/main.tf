terraform {
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
  version = "~> 20.0"

  cluster_name    = "deployhub-cluster"
  cluster_version = "1.29"

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  # Base node group — platform services, ArgoCD, controller, worker
  eks_managed_node_groups = {
    platform_nodes = {
      min_size       = 1
      max_size       = 3
      desired_size   = 2
      instance_types = ["t3.medium"]

      labels = {
        "deployhub.jeneeldumasia.codes/node-type" = "platform"
      }
    }
  }

  enable_cluster_creator_admin_permissions = true
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

# ── ECR Repository ────────────────────────────────────────────────────────────
# Task 5: ECR repo for built tenant images.
# Builder pushes here; tenant pods pull from here via IRSA.
resource "aws_ecr_repository" "builds" {
  name                 = "deployhub-builds"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # Clean up on destroy — matches teardown-per-session workflow
  force_delete = true
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
  value       = module.iam_github_oidc_role.iam_role_arn
}

# ── Route53 & Cert-Manager ───────────────────────────────────────────────────
data "aws_route53_zone" "deployhub" {
  name         = "jeneeldumasia.codes"
  private_zone = false
}

module "irsa_cert_manager" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "DeployHubCertManager"

  attach_cert_manager_policy = true
  cert_manager_hosted_zone_arns = [data.aws_route53_zone.deployhub.arn]

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["cert-manager:cert-manager"]
    }
  }
}

# ── Karpenter ────────────────────────────────────────────────────────────────
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.0"

  cluster_name = module.eks.cluster_name

  enable_pod_identity  = false
  create_iam_role      = true
  iam_role_name        = "DeployHubKarpenterController"
  create_node_iam_role = true
  node_iam_role_name   = "DeployHubKarpenterNodeRole"
  create_access_entry  = true
  
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}

output "route53_hosted_zone_id" {
  description = "Route53 Hosted Zone ID for cert-manager DNS-01 challenges"
  value       = data.aws_route53_zone.deployhub.zone_id
}

