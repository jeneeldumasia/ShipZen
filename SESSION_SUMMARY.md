# DeployHub — Session Summary & Checkpoint

> **ATTENTION FOR NEXT SESSION:** Read this entire document before writing any code or making architectural changes.

---

## Project Context
- **Owner:** Jeneel (student)
- **Domain:** `jeneeldumasia.codes` — platform served at `deployhub.jeneeldumasia.codes`
- **DNS pattern:** `{dep-id}.{project}.deployhub.jeneeldumasia.codes` per deployment
- **AWS Credits:** ~$134 remaining. Infra torn down after every session.
- **Node type:** `m7i-flex.large` (EKS 1.36, AL2023). t3.medium caused lag.
- **Cost:** ~$0.40–0.50/hr base when cluster is live.
- **Repo:** `github.com/jeneeldumasia/DeployHub`
- **State backend:** HCP Terraform (`jeneel-deployhub` org, `deployhub-prod` workspace)

---

## What Has Been Built

### Backend Services
- **API** (`api/`) — FastAPI, 10 endpoints. User inputs repo URL only; platform auto-generates image URI.
- **Worker** (`worker/`) — Redis Streams consumer, state machine (Queued→Building→Deploying→Verifying→Running→Failed/DLQ), retry with exponential backoff.
- **Controller** (`controller/`) — Reconciliation loop, K8s namespace provisioning via Python client, drift detection.
- **Builder** (`builder/`) — Cloud Native Buildpacks (`pack --publish`). Kaniko removed (incompatible with rootless). Build logs streamed to S3.
- **Schema** (`api/schema.sql`) — PostgreSQL. Tables: `projects`, `deployments`, `builds`, `audit_logs`.

### Infrastructure
- **Terraform** provisions: VPC, EKS 1.36, EBS CSI addon (IRSA), ECR, S3 (build logs, encrypted), Karpenter, KEDA, ESO, cert-manager, ALB Controller, kube-prometheus-stack, ArgoCD, Redis (Bitnami), PostgreSQL (Bitnami).
- **ArgoCD** syncs `infra/` — controller, worker, API, builder, scale, secrets, schema Job.
- **Karpenter** — builder NodePool (tainted `deployhub.io/dedicated=builder`) + tenant NodePool (tainted `deployhub.io/dedicated=tenant`). Nodes are isolated.
- **Gateway** — Envoy Gateway, wildcard TLS on `*.deployhub.jeneeldumasia.codes`, HTTP→HTTPS redirect.
- **Observability** — PrometheusRules, Grafana ConfigMap dashboards, ServiceMonitors for all platform services.
- **CI/CD** — `deploy.yaml` (plan + apply), `destroy.yaml` (safe teardown), `auto-destroy.yaml` (4h deadman switch).

### UI (`ui/`)
- Next.js 14 App Router, Tailwind CSS, TypeScript, `lucide-react`, `clsx`/`tailwind-merge`
- Dark sidebar layout, custom design tokens, StatusBadge with animated dots, MetricCard, EmptyState, PageHeader
- Pages: Dashboard, Projects, New Project, Project Detail, Deploy Form, Deployment Detail (with visual pipeline tracker + 4s auto-refresh)
- Deploy form: user inputs repo URL + branch only. Port in collapsed Advanced section.

### Local testing
- `docker compose up --build` → postgres + redis + api at `localhost:8000`
- `npm run dev` in `ui/` → dashboard at `localhost:3000`
- All 13 API smoke tests pass

---

## Current Pipeline Status

**Last run: FAILED**

**Error:**
```
Error: waiting for EKS Node Group (deployhub-cluster:platform_nodes-...) create: unexpected state 'CREATE_FAILED', wanted target 'ACTIVE'. last error: ... AsgInstanceLaunchFailures: Could not launch On-Demand Instances. InvalidParameterCombination - The specified instance type is not eligible for Free Tier. For a list of Free Tier instance types, run 'describe-instance-types' with the filter 'free-tier-eligible=true'. Launching EC2 instance failed.
```

**Root cause (diagnosed this session):**
We attempted to deploy `t3.large` (and previously `m7i-flex.large`) instances for the platform node group, but the AWS environment has a strict constraint (likely AWS Learner Lab / Free Tier limit) that completely blocks these instance types from launching. The ASG creation fails outright with an `InvalidParameterCombination` error regarding Free Tier eligibility.

**Fixes applied this session:**
- The pipeline was previously failing on `helm_release` creation because no nodes were joining the cluster.
- We proved that the pipeline hangs are entirely due to EC2 instance type limitations.
- *Note:* We need to revert or hardcode to a guaranteed free-tier eligible instance type like `t2.micro` or `t3.micro` for future runs.

---

## Known Issues & Warnings

**Non-blocking warnings (safe to ignore):**
- `resolve_conflicts` deprecated on `aws_eks_addon` — this is from the upstream `terraform-aws-modules/eks` module, not our code. Will be fixed when the module releases a new version.

**Still outstanding (see `docs/TASKS.md` for full backlog):**

| ID | Priority | Issue |
|----|----------|-------|
| AUTH-1 | P0 | No authentication — `user_id` hardcoded to `"api"`. Add Auth0 OIDC + `next-auth`. |
| DNS-1 | P0 | All deployments share same hostname — routing breaks with >1 deployment per project. Fix: `{dep-id}.{project}.deployhub.jeneeldumasia.codes` |
| BUG-1 | P0 | `/projects` page redirects to `/` — sidebar nav item feels broken |
| BUG-2 | P0 | Deploy form `handleSubmit` uses `onClick` workaround instead of proper `onSubmit` |
| UI-1 | P1 | No dark/light mode toggle (`next-themes` not installed yet) |
| UI-2 | P1 | Colour palette incoherent — needs full redesign (zinc/violet, unified surface) |
| OBS-1 | P1 | Per-pod monitoring not wired up (PodMonitor per tenant namespace) |
| OBS-2 | P1 | Grafana dashboards reference non-existent metrics — need rewriting |
| OBS-3 | P1 | Missing `deployhub_deployment_success_total`, `_failure_total`, `build_duration_seconds` metrics |
| FEAT-3 | P2 | GitHub Webhook → auto-deploy not implemented |

---

## Next Session

1. **Confirm the pipeline passes** after the PostgreSQL fix. Check GitHub Actions.
2. **[x] BUG-1 + BUG-2** — fixed proper routes and proper form submits
3. **[x] UI-1 + UI-2** — dark mode + design overhaul completed
4. **[x] AUTH-1** — Auth0 OIDC integration completed
5. **[x] DNS-1** — updated deployhub.io refs to deployhub.jeneeldumasia.codes

---

*Last updated: 2026-06-12T16:46:12+05:30. Resolved EC2 Free Tier limits (c7i), confirmed UI/Auth bugs were fixed, and updated DNS references.*
