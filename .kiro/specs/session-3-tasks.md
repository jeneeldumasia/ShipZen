# Implementation Plan:

## Overview
Complete the missing infrastructure and API server so DeployHub can run end-to-end. Covers Terraform operator installs, Kubernetes Deployment manifests, the FastAPI server, and remaining high-priority bug fixes from the Session 2 audit.

## Tasks
- [x] 1. Create `terraform/redis.tf` — Bitnami Redis Helm release, namespace `deployhub-system`, single master, no persistence
- [x] 2. Create `terraform/postgres.tf` — Bitnami PostgreSQL Helm release, namespace `deployhub-system`, 10Gi PVC, db `deployhub`, writes `deployhub-db-credentials` secret
- [x] 3. Create `terraform/operators.tf` — KEDA, ESO, and AWS Load Balancer Controller Helm releases with IRSA for ALB Controller
- [x] 4. Create `terraform/monitoring.tf` — kube-prometheus-stack, namespace `observability`, persistence disabled
- [x] 5. Add ECR repository `deployhub-builds` and `aws_caller_identity` data source to `terraform/main.tf`; add outputs for `ecr_repository_url`, `build_logs_bucket_name`, `aws_account_id`
- [x] 6. Scope GitHub Actions IAM role down from `AdministratorAccess` to minimum permissions; restrict subject from wildcard `*` to `ref:refs/heads/main`
- [x] 7. Create `infra/system/namespace.yaml` — `deployhub-system` namespace with system label
- [x] 8. Create `infra/system/schema-configmap.yaml` and `infra/system/schema-job.yaml` — one-shot Job to bootstrap `api/schema.sql` into PostgreSQL on cluster start
- [x] 9. Create `infra/system/servicemonitors.yaml` — ServiceMonitor and Service resources for worker (8000), controller (9090), and API server (8000)
- [x] 10. Create `infra/controller/deployment.yaml`, `serviceaccount.yaml`, `kustomization.yaml`
- [x] 11. Create `infra/worker/deployment.yaml`, `serviceaccount.yaml`, `kustomization.yaml`
- [x] 12. Create `infra/api/deployment.yaml`, `service.yaml`, `kustomization.yaml`
- [x] 13. Create top-level `infra/kustomization.yaml` referencing all sub-directories so ArgoCD syncs everything
- [x] 14. Create `api/main.py` — FastAPI server with projects CRUD, deployments, builds, audit, and healthz endpoints
- [x] 15. Create `api/requirements.txt` and `api/Dockerfile`
- [x] 16. Remove Kaniko from `builder/main.py` — always use `pack --publish`; update `builder/Dockerfile` to remove Kaniko executor download
- [x] 17. Fix tenant RBAC in `controller/templates/tenant.yaml.j2` — remove `secrets` from tenant-runner Role resources
- [x] 18. Fix hardcoded `123456789012` AWS account ID in `infra/builder/serviceaccount.yaml` and `infra/secrets/cluster-secret-store.yaml`
- [x] 19. Fix hardcoded `us-east-1` region in `infra/secrets/cluster-secret-store.yaml`

## Task Dependency Graph
```json
{
  "waves": [
    { "wave": 1, "tasks": [1, 2, 3, 4, 5, 7, 16, 17, 18, 19], "description": "Terraform operator installs, ECR/outputs, system namespace, and independent fixes — all parallelizable" },
    { "wave": 2, "tasks": [6, 8, 14], "description": "IAM scope (needs outputs from task 5), schema Job (needs namespace from task 7), API code (needs requirements from task 15)" },
    { "wave": 3, "tasks": [10, 11, 15], "description": "Controller and worker manifests (schema must exist), API Dockerfile/requirements" },
    { "wave": 4, "tasks": [9, 12], "description": "ServiceMonitors (need services to exist), API infra manifests (need API code from task 15)" },
    { "wave": 5, "tasks": [13], "description": "Top-level kustomization — ties everything together once all sub-directories exist" }
  ]
}
```

## Notes
- Redis persistence is intentionally disabled — the deploy queue is ephemeral and sessions are torn down after each run
- PostgreSQL persistence is enabled (10Gi) so the schema survives pod restarts within a session, but is destroyed with the cluster on teardown
- The schema Job uses `restartPolicy: OnFailure` — if it runs again on a re-deploy it will be a no-op because all tables use `CREATE TABLE IF NOT EXISTS`
- The GitHub Actions IAM scope change (task 6) requires a `terraform apply` to take effect; the existing `secrets.AWS_ROLE_ARN` secret does not change — only the permissions attached to the role change
- Kaniko removal (task 16) simplifies the builder significantly — `pack` handles both Dockerfile and non-Dockerfile repos natively via its detection logic
