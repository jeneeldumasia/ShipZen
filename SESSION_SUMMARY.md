# ShipZen — Session Summary & Checkpoint

> **ATTENTION FOR NEXT SESSION:** Read this entire document and the `implementation_plan.md` artifact before writing any code or making architectural changes.

---

## Project Context
- **Owner:** Jeneel (student)
- **Domain:** `jeneeldumasia.codes` — platform served at `shipzen.jeneeldumasia.codes`
- **DNS pattern:** `{dep-id}.{project}.shipzen.jeneeldumasia.codes` per deployment
- **AWS Credits:** ~$134 remaining. Infra torn down after every session.
- **Node type:** `m7i-flex.large` (EKS 1.36, AL2023). t3.medium caused lag.
- **Cost:** ~$0.40–0.50/hr base when cluster is live.
- **Repo:** `github.com/jeneeldumasia/ShipZen`
- **State backend:** HCP Terraform (`jeneel-shipzen` org, `shipzen-prod` workspace)

---

## Architectural Decisions This Session (June 19)

We finalized the **3-Tier Ephemeral Builder** architecture to support zero-config "deploy anything" without introducing a permanent, shared blast radius.

1. **Tier 1 (Buildpacks):** The default fallback. Runs `pack` rootless in `shipzen-builder`.
2. **Tier 2 (Dockerfile):** If `Dockerfile` exists, run BuildKit in `shipzen-builder-privileged`.
3. **Tier 3 (Railpack):** If complex/mixed repo (e.g., `Cargo.toml`, `bun.lockb`), run Railpack natively in `shipzen-builder-privileged`.

**Key Operational Agreements:**
- **No Shared BuildKit Farm:** Every build is a single-use Kubernetes `Job` that instantly terminates.
- **Detector Framework:** Routing is deterministic via `DockerfileDetector`, `RailpackDetector`, etc., not probabilistic.
- **Telemetry:** Schema will be updated to track `builder_type`, `build_duration_sec`, and cache ratios.
- **Caching:** We will use ECR Lifecycle rules to prune `cache-buildpacks` and `cache-railpack` registries.
- **Security:** Privileged Jobs are strictly constrained by NodePool caps (max 5 nodes), 15-minute active deadline timeouts, and 2vCPU/4Gi limits.

---

## What Has Been Built

### Backend Services
- **API** (`api/`) — FastAPI, 10 endpoints. User inputs repo URL only; platform auto-generates image URI.
- **Worker** (`worker/`) — Redis Streams consumer, state machine (Queued→Building→Deploying→Verifying→Running→Failed/DLQ), retry with exponential backoff. *(Note: pending major refactor to spawn K8s Jobs instead of pushing to builder queue).*
- **Controller** (`controller/`) — Reconciliation loop, K8s namespace provisioning via Python client, drift detection.
- **Builder** (`builder/`) — *(Note: transitioning from KEDA-scaled Redis consumer to single-use K8s Jobs).*
- **Schema** (`api/schema.sql`) — PostgreSQL. Tables: `projects`, `deployments`, `builds`, `audit_logs`.

### Infrastructure
- **Terraform** provisions: VPC, EKS 1.36, EBS CSI addon (IRSA), ECR, S3 (build logs, encrypted), Karpenter, KEDA, ESO, cert-manager, ALB Controller, kube-prometheus-stack, ArgoCD, Redis (Bitnami), PostgreSQL (Bitnami).
- **ArgoCD** syncs `infra/` — controller, worker, API, builder, scale, secrets, schema Job.
- **Karpenter** — builder NodePool (tainted `shipzen.io/dedicated=builder`) + tenant NodePool (tainted `shipzen.io/dedicated=tenant`).
- **Gateway** — Envoy Gateway, wildcard TLS on `*.shipzen.jeneeldumasia.codes`, HTTP→HTTPS redirect.

### UI (`ui/`)
- Next.js 14 App Router, Tailwind CSS, TypeScript, `lucide-react`.
- Pages: Dashboard, Projects, New Project, Project Detail, Deploy Form, Deployment Detail (with visual pipeline tracker).

---

## Known Issues & Warnings

**Still outstanding (see `docs/TASKS.md` for full backlog):**
| ID | Priority | Issue |
|----|----------|-------|
| OBS-1 | P1 | Per-pod monitoring not wired up (PodMonitor per tenant namespace) |
| OBS-2 | P1 | Grafana dashboards reference non-existent metrics — need rewriting |
| OBS-3 | P1 | Missing `shipzen_deployment_success_total`, `_failure_total`, `build_duration_seconds` metrics |
| FEAT-3 | P2 | GitHub Webhook → auto-deploy not implemented |

---

## Next Session: Execution Phase

We will execute the `task.md` created this session:
1. **BuildKit PoC:** Validate required `securityContext` to run `moby/buildkit` rootless/privileged inside EKS.
2. **Schema Upgrades:** Add new build telemetry fields.
3. **Worker Refactor:** Implement the `Builder` detector framework and rip out the Redis `builder_queue`.
4. **Job Orchestration:** Generate dynamic restricted/privileged K8s Job manifests and stream logs back to Redis/S3.
5. **Terraform/Infra:** Configure the `shipzen-builder-privileged` namespace, ECR Lifecycle policies, and NodePool taints.

---

*Last updated: 2026-06-19. Finalized 3-Tier Ephemeral Builder architecture.*

## Architectural Decisions This Session (June 23)
- Fixed Karpenter EKS Pod Identity Webhook bug by hardcoding AWS_ROLE_ARN and projected volume tokens.
- Addressed AWS Secrets Manager sync issues (fixed typos and created dummy secrets to unblock API startup).
- Resolved ArgoCD delay issues by patching 	imeout.reconciliation to 10 seconds.
- Identified Cloudflare Edge-to-Origin SSL mismatch: API subdomain was not covered by the Terraform-provisioned Origin CA cert. 
- Implemented **Path-Based Routing** for the API (/api/v1/* -> shipzen-api) to reuse the UI's valid Cloudflare Edge SSL certificate.
- Identified the Build failure: shipzen-worker requires the same Pod Identity hardcoding as Karpenter to authorize S3 PutObject for build logs.

## Next Session (June 23 Continued)
1. **Worker Pod Identity**: Patch infra/worker/deployment.yaml with explicit projected volume and AWS_ROLE_ARN for shipzen-worker so it can upload logs to S3.
2. Verify Kaniko builds succeed and stream logs correctly.
