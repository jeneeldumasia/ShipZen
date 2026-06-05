# Session 3 — Infrastructure Completion & API Server

## Overview
The DeployHub backend engine is built and its bugs fixed. This session completes the missing infrastructure so the system can actually run end-to-end: operators installed, services deployed, schema applied, and the API server built.

The platform teardown-per-session constraint is in effect (AWS student credits). All infra must be cleanly destroyable via the existing `destroy.yaml` workflow.

## Requirements

### 1. Terraform — Operator & Dependency Installs

Install all missing cluster dependencies as Helm releases in Terraform so they are provisioned automatically on `terraform apply` and destroyed on `terraform destroy`.

#### 1.1 Redis
- Install Bitnami Redis via `helm_release` in a new `terraform/redis.tf`
- Namespace: `deployhub-system`
- Single master, no replicas (cost: student account)
- Persistence disabled (data is ephemeral queue — acceptable)
- Service name must resolve to `redis-master.deployhub-system.svc.cluster.local` to match existing service references in worker and builder
- `depends_on` EKS

#### 1.2 PostgreSQL
- Install Bitnami PostgreSQL via `helm_release` in `terraform/postgres.tf`
- Namespace: `deployhub-system`
- Single instance, no replicas
- Persistence enabled with a small PVC (10Gi)
- Database name: `deployhub`, username: `deployhub`
- Password stored as a Kubernetes Secret, referenced by name `deployhub-db-credentials` with key `url` (full connection string) — this matches the `secretKeyRef` already in `infra/builder/deployment.yaml`
- `depends_on` EKS

#### 1.3 KEDA
- Install KEDA via `helm_release` in `terraform/operators.tf`
- Namespace: `keda`
- Use the official KEDA Helm chart (`kedacore/keda`)
- `depends_on` EKS

#### 1.4 External Secrets Operator (ESO)
- Install ESO via `helm_release` in `terraform/operators.tf`
- Namespace: `external-secrets`
- Use the official ESO Helm chart (`external-secrets/external-secrets`)
- `depends_on` EKS

#### 1.5 kube-prometheus-stack
- Install via `helm_release` in `terraform/monitoring.tf`
- Namespace: `observability`
- Grafana enabled, Prometheus enabled
- Persistence disabled (cost)
- `depends_on` EKS

#### 1.6 AWS Load Balancer Controller
- Install via `helm_release` in `terraform/operators.tf`
- Required for the Gateway's NLB annotation to work
- Needs an IRSA role with `elasticloadbalancing:*` and `ec2:Describe*` permissions
- `depends_on` EKS

#### 1.7 Scope the GitHub Actions IAM role (fix #4.2)
- In `terraform/main.tf`, replace `AdministratorAccess` with a minimal inline policy covering only:
  - `eks:*` on the cluster ARN
  - `ecr:*` on all ECR repos in the account
  - `s3:*` on the build logs bucket ARN
  - `iam:PassRole` scoped to the builder and ESO roles
- Subject must be scoped to `repo:jeneeldumasia/DeployHub:ref:refs/heads/main` (not wildcard `*`)

#### 1.8 ECR Repository (fix #8.8)
- Add `aws_ecr_repository` resource in `terraform/main.tf` named `deployhub-builds`
- Output the repository URL as `ecr_repository_url`
- Add a Terraform output that also writes the bucket name as `build_logs_bucket_name`

### 2. infra/ — Missing Deployment Manifests

#### 2.1 deployhub-system namespace
- Create `infra/system/namespace.yaml` for the `deployhub-system` namespace with label `deployhub.io/system: "true"`

#### 2.2 Controller Deployment
- Create `infra/controller/deployment.yaml`
- Namespace: `deployhub-system`
- Single container running `deployhub-controller:latest`
- Env vars via `secretKeyRef` from `deployhub-db-credentials` for `DATABASE_URL`
- `RECONCILIATION_INTERVAL` env var defaulting to `"60"`
- Resource requests: 100m CPU, 128Mi memory. Limits: 500m CPU, 256Mi
- `imagePullPolicy: Always` (so new builds are picked up)
- ServiceAccount: `deployhub-controller-sa`
- Liveness probe: HTTP GET `/healthz` on port 9090 (the metrics port), initialDelaySeconds 15
- Create `infra/controller/serviceaccount.yaml`
- Create `infra/controller/kustomization.yaml` referencing all controller manifests

#### 2.3 Worker Deployment
- Create `infra/worker/deployment.yaml`
- Namespace: `deployhub-system`
- Single container running `deployhub-worker:latest`
- Env vars: `DATABASE_URL` from `deployhub-db-credentials`, `REDIS_HOST` value `redis-master.deployhub-system.svc.cluster.local`, `STREAM_NAME` value `deploy_stream`, `CONSUMER_GROUP` value `worker_group`, `BUILDER_QUEUE_NAME` value `builder_queue`
- Resource requests: 100m CPU, 128Mi memory. Limits: 500m CPU, 256Mi
- `imagePullPolicy: Always`
- ServiceAccount: `deployhub-worker-sa`
- Create `infra/worker/serviceaccount.yaml`
- Create `infra/worker/kustomization.yaml`

#### 2.4 API Server Deployment
- Create `infra/api/deployment.yaml`
- Namespace: `deployhub-system`
- Single container running `deployhub-api:latest`, port 8000
- Env vars: `DATABASE_URL` from `deployhub-db-credentials`, `REDIS_HOST`, `STREAM_NAME`
- Service: ClusterIP on port 80 → 8000
- Create `infra/api/service.yaml`
- Create `infra/api/kustomization.yaml`

#### 2.5 Schema Bootstrap Job
- Create `infra/system/schema-job.yaml`
- A Kubernetes `Job` that runs once on cluster bootstrap to apply `api/schema.sql`
- Uses `postgres:15-alpine` image
- Runs `psql $DATABASE_URL -f /schema/schema.sql`
- Mounts `schema.sql` via a `ConfigMap` (`infra/system/schema-configmap.yaml`)
- `restartPolicy: OnFailure`
- This solves the missing schema bootstrap problem (#8.1 medium)

#### 2.6 Update infra/ kustomization
- Create a top-level `infra/kustomization.yaml` that references all sub-directories so ArgoCD syncs everything from `path: infra`

### 3. API Server (Phase 16)

Build a FastAPI HTTP server in `api/main.py` that is the sole entry point for developers to interact with DeployHub.

#### 3.1 Endpoints

**Projects**
- `POST /projects` — create a project. Body: `{ name, namespace }`. Validates namespace is DNS-safe. Inserts into `projects` table with status `Provisioning`. Logs audit event. Returns `201` with the project object.
- `GET /projects` — list all non-deleted projects
- `GET /projects/{project_id}` — get a single project
- `DELETE /projects/{project_id}` — soft-delete: sets `status = Terminating`. Controller picks it up.

**Deployments**
- `POST /projects/{project_id}/deployments` — submit a deployment. Body: `{ repo_url, image_name, replicas?, port? }`. Validates `repo_url` against the same allowlist used in the builder (`https://` or `git@`). Inserts into `deployments` table with state `Queued`. Enqueues to Redis stream `deploy_stream` with `deployment_id`, `repo_url`, `image_name`, `queued_at`. Logs audit event. Returns `202`.
- `GET /projects/{project_id}/deployments` — paginated list using keyset pagination from `api/database.py`
- `GET /projects/{project_id}/deployments/{deployment_id}` — get deployment status and last error

**Builds**
- `GET /projects/{project_id}/deployments/{deployment_id}/builds` — list builds for a deployment, ordered by `started_at DESC`

**Audit**
- `GET /projects/{project_id}/audit` — list audit logs for a project (uses `api/audit.py`)

**Health**
- `GET /healthz` — returns `{"status": "ok"}` always. Used by liveness probe.

#### 3.2 Implementation details
- Use FastAPI with Pydantic v2 request/response models
- Use the existing `api/database.py` `get_connection()` for DB access — no ORM
- Use the existing `api/audit.py` `log_audit_event()` for all state-changing endpoints
- Redis connection: `redis.Redis` using `REDIS_HOST` env var, stream name from `STREAM_NAME` env var
- All DB errors return `500` with a safe message (no raw exception text to client)
- Namespace validation: must match `^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$`
- `repo_url` validation: same regex allowlist as `builder/main.py`
- Add `api/requirements.txt` with `fastapi`, `uvicorn[standard]`, `psycopg2-binary`, `redis`, `pydantic`
- Add `api/Dockerfile` — `python:3.11-slim`, installs requirements, runs `uvicorn api.main:app --host 0.0.0.0 --port 8000`

### 4. Fix Remaining High-Priority Issues

#### 4.1 Fix Kaniko security context (fix #4.4)
- In `infra/builder/deployment.yaml`, Cloud Native Buildpacks (`pack`) is rootless-compatible
- Kaniko requires filesystem overlay — it cannot run with `runAsNonRoot: true` + all caps dropped
- Solution: split the security context. Keep `runAsNonRoot` at the pod level but add a dedicated Kaniko sidecar with a relaxed context, OR — simpler — switch the builder to use only `pack` (Buildpacks) for all builds and remove the Kaniko path from `builder/main.py`
- Implement the simpler approach: remove Kaniko from `builder/main.py`, always use `pack --publish`. The Dockerfile detection logic is unnecessary overhead — Buildpacks handle both cases natively.
- Update `builder/Dockerfile` to remove the Kaniko executor download

#### 4.2 Fix tenant RBAC (fix #4.7)
- In `controller/templates/tenant.yaml.j2`, the `tenant-runner` Role grants `get`/`list`/`watch` on all `secrets` in the namespace
- Tighten to only allow `get` on secrets with names matching the deployment's own secret (use `resourceNames` if the secret name is known, or remove `secrets` from the role entirely since the app container gets secrets via `envFrom` — it doesn't need to call the K8s API for them)
- Remove `secrets` from the Role's resources. Apps get their secrets injected as env vars by ESO — they have no reason to call the K8s secrets API directly.

#### 4.3 Add ServiceMonitor resources (fix #6.4)
- Create `infra/system/servicemonitors.yaml` with `ServiceMonitor` resources for:
  - `deployhub-worker` scraping port 8000
  - `deployhub-controller` scraping port 9090
  - `deployhub-api` scraping port 8000
- Add matching `Service` objects (ClusterIP, no external access) for worker and controller to expose their metrics ports

#### 4.4 Fix hardcoded AWS account ID (fix #4.1)
- In `infra/builder/serviceaccount.yaml` and `infra/secrets/cluster-secret-store.yaml`, replace hardcoded `123456789012` with a Terraform output or a placeholder comment instructing use of `terraform output aws_account_id`
- Add `data "aws_caller_identity" "current" {}` in `terraform/main.tf` and output `aws_account_id = data.aws_caller_identity.current.account_id`

#### 4.5 Fix ClusterSecretStore region (fix #5.9)
- In `infra/secrets/cluster-secret-store.yaml`, replace hardcoded `us-east-1` with a comment referencing `var.aws_region`, and add a note that this file should be templated or replaced with a Terraform `kubernetes_manifest` resource that injects the region dynamically

## Acceptance Criteria

- `terraform apply` provisions: VPC, EKS, Redis, PostgreSQL, KEDA, ESO, kube-prometheus-stack, ALB Controller, ArgoCD, ECR repo, S3 bucket
- `terraform destroy` (via the destroy workflow) cleans up everything with no leftover resources
- ArgoCD syncs `infra/` and deploys: controller, worker, API server, builder (KEDA-managed), schema bootstrap job
- `POST /projects` and `POST /projects/{id}/deployments` return correct responses
- `GET /healthz` returns 200
- Worker and controller metrics are scraped by Prometheus (ServiceMonitors exist)
- GitHub Actions IAM role is scoped to minimum required permissions
