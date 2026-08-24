# Current State: ShipZen

## Current Development Phase
We are currently finalizing the platform's infrastructure deployment for production readiness. The foundational codebase (UI, API, Worker, Controller, Terraform) is in place, and we are stabilizing the AWS deployment pipeline.

## Recently Completed Changes
* **Pre-Deployment Infrastructure Audit Fixes**: Addressed all CRIT-to-LOW issues before the final production deploy.
* **Hardcoded Account IDs Removed**: Updated IAM annotations and ECR repository endpoints to properly reference the new AWS account ID dynamically.
* **Secrets Push Automation**: Integrated inline AWS Secrets Manager pushing into the `.github/workflows/deploy.yaml` GitHub Actions pipeline.
* **IAM Privileges Lockout Fixed**: Resolved the classic IAM chicken-and-egg problem where the GitHub Actions CI/CD role could not update its own policy.
* **Kyverno Security Policies**: Configured Kyverno runtime security, but successfully added an exemption for the `observability` namespace to permit Prometheus `node-exporter` (which fundamentally requires host access).

## Known Technical Debt / Blockers
* **GitHub OAuth/App Webhooks**: Now that the infrastructure is deploying, we need to ensure the GitHub App is correctly registered and its webhook endpoint points to the new ALB endpoint.
* **Secrets Synchronization**: The External Secrets Operator relies on the stub secrets we pushed. If any real secrets are missing in AWS Secrets Manager, pods may fail to start.

## Anything That May Surprise Another Developer/AI
* **Strict GitOps Pipeline**: Do NOT attempt to run `terraform apply` locally or use `aws` CLI locally to create resources. The CI/CD role (`ShipZenGitHubActionsPolicy`) must manage the state via `.github/workflows/deploy.yaml`.
* **Kyverno Enforcement**: Tenant namespaces run under strict pod security policies. If you add new daemonsets or privileged workloads, they will fail to deploy unless added to a `PolicyException` or deployed in a trusted namespace like `observability` or `kube-system`.
