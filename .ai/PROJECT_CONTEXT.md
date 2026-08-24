# Project Context: ShipZen

## Purpose
ShipZen is a multi-tenant Platform-as-a-Service (PaaS) built on Kubernetes, designed to behave like Vercel or Heroku. Users authenticate with GitHub, connect repositories, and ShipZen automatically builds and deploys their code to an EKS cluster.

## Tech Stack
* **Frontend**: Next.js (App Router), React, NextAuth (GitHub OAuth)
* **Backend API**: Python, FastAPI, WebSockets
* **Background Worker**: Custom Python worker (Redis queue)
* **Kubernetes Controller**: Custom Python operator (Jinja2 templating, kubernetes client)
* **Database**: PostgreSQL (psycopg2) for state and RBAC, Redis for queues/caching
* **Infrastructure**: AWS (EKS, RDS, S3, Secrets Manager, ECR, CloudWatch) managed via Terraform
* **Cluster Addons**: ArgoCD (GitOps), Kyverno (Runtime Security), Karpenter (Autoscaling), External Secrets Operator, Prometheus & Grafana
* **CI/CD**: GitHub Actions

## Architecture & Data Flow
1. **User Action**: User connects a repo in the UI. UI calls the FastAPI backend.
2. **Database**: API creates `projects`, `deployments`, and `builds` records in PostgreSQL.
3. **Build Phase**: API queues a build in Redis. The Python `worker` picks it up, runs the build, pushes the image to ECR (`shipzen-builds`), and streams logs to S3.
4. **Deploy Phase**: The Python `controller` detects the successful build, generates Kubernetes manifests, and deploys them for the tenant.
5. **Observability**: Prometheus scrapes metrics, Grafana visualizes them. Kyverno enforces Baseline/Restricted pod security on all tenant namespaces.

## Important Directories
* `ui/`: Next.js frontend code
* `api/`: FastAPI backend and database schema (`schema.sql`)
* `worker/`: Python build/task processor
* `controller/`: Python Kubernetes operator
* `terraform/`: Infrastructure-as-Code (AWS + Helm charts)
* `infra/`: Base Kubernetes manifests (ArgoCD manages these)
* `.github/workflows/`: CI/CD deployment pipelines

## Architectural Rules
* **Strict GitOps**: No manual infrastructure changes. All infra changes go through GitHub Actions.
* **Separation of Concerns**: Tenant workloads are strictly isolated from system workloads.
* **Append-Only Auditing**: The `audit_logs` table enforces append-only rules via database triggers.
* **Production Standards**: No "dev" shortcuts. Use real lifecycle policies, IAM roles (IRSA), and persistent volumes.

## Future AI Startup Protocol
When starting a new development session:
1. Read `.ai/PROJECT_CONTEXT.md`
2. Read `.ai/CURRENT_STATE.md`
3. Read `.ai/HANDOFF.md`
4. Read `.ai/TASKS.md`
5. Read `.ai/DECISIONS.md` when making architectural changes
6. Identify the specific files relevant to the requested task
7. Inspect only those files unless broader investigation is necessary
8. Do NOT perform a full repository scan by default
9. Treat the source code as authoritative if it conflicts with stale context documentation
10. Update the relevant `.ai/` files after completing meaningful changes
