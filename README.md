# DeployHub — Production Internal Developer Platform (IDP)

DeployHub is an enterprise-grade Internal Developer Platform built from scratch to orchestrate Kubernetes deployments seamlessly. 

The platform features strict multi-tenant isolation, native Cloud Native Buildpacks (with Kaniko fallback), an asynchronous Python Controller polling PostgreSQL for state reconciliation, and Envoy Gateway for host-based routing.

## 🚀 GitHub Actions Configuration

Before running the GitHub Actions deployment pipeline, you **must** configure the following **Repository Secrets** in your GitHub repository settings (`Settings > Secrets and variables > Actions`):

### Required AWS Secrets
- `AWS_ACCOUNT_ID`: Your 12-digit AWS account ID.
- `AWS_REGION`: The target AWS region (e.g., `us-east-1`).
- `AWS_ROLE_ARN`: The ARN of the IAM Role configured for GitHub Actions OIDC federation. This role must have permissions to push to ECR and deploy manifests to EKS.

### Required Infrastructure Configuration
- `EKS_CLUSTER_NAME`: The name of the target EKS cluster.
- `POSTGRES_PASSWORD`: The initial password for the PostgreSQL master user.
- `REDIS_PASSWORD`: The initial password for the Redis cluster.

## 🏗️ Architecture

- **Worker (`worker/`):** Asynchronous Python daemon handling Redis Streams to orchestrate deployment tasks.
- **Builder (`builder/`):** Autoscaling pool using Cloud Native Buildpacks (`pack`) for rootless container generation, streaming logs directly to S3.
- **Controller (`controller/`):** Python-based continuous Reconciliation Engine resolving drift against PostgreSQL desired state.
- **Gateway (Envoy Gateway):** Managed via ArgoCD, providing strict TLS-terminated wildcard host routing.

For deeper technical specifics, Threat Models, and Architecture Diagrams, please consult the `docs/` directory.
