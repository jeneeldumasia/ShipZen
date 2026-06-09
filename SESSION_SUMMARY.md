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
Error: context deadline exceeded
  with helm_release.postgresql
  on postgres.tf line 18
```

**Root cause (diagnosed this session):**
The PostgreSQL Helm release timed out because its PVC could not be provisioned. Three combined problems:

1. **No StorageClass specified** — the release used the cluster default. On EKS 1.36 + AL2023, the default StorageClass behaviour is less predictable than on older clusters. The PVC stayed `Pending`.
2. **Wrong `depends_on`** — PostgreSQL depended on `helm_release.keda` and `helm_release.karpenter`. Postgres runs on the managed node group and has nothing to do with Karpenter. The real dependency is the **EBS CSI addon**, which is defined inside `module.eks`. Without waiting for the CSI controller pod to reach Running, the PVC provisioner isn't available.
3. **Timeout too low** — 600s (10 min) is too tight on a cold cluster boot where Karpenter may be provisioning nodes for other workloads simultaneously.

**Fixes applied this session:**
- `terraform/postgres.tf` — added `primary.persistence.storageClass = "gp2"` explicitly
- `terraform/postgres.tf` — replaced `depends_on [keda, karpenter]` with `depends_on [time_sleep.wait_for_ebs_csi]`
- `terraform/postgres.tf` — added `time_sleep.wait_for_ebs_csi` (45s after `module.eks`) to let the CSI controller pod reach Running before any PVC is created
- `terraform/postgres.tf` — increased timeout to 900s (15 min)
- `terraform/operators.tf` — pinned KEDA to `2.14.2`, Karpenter to `1.0.6` (were unpinned)
- `terraform/operators.tf` — fixed KEDA `depends_on` (was incorrectly depending on ESO)
- `terraform/main.tf` — fixed `github_actions_role_arn` output (`module.iam_github_oidc_role.arn` → `module.iam_github_oidc_role.iam_role_arn`)

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
2. **BUG-1 + BUG-2** — quick fixes (30 min)
3. **UI-1 + UI-2** — dark mode + design overhaul (do together)
4. **AUTH-1** — Auth0 OIDC integration (biggest remaining piece)
5. **DNS-1** — update all `deployhub.io` refs to `deployhub.jeneeldumasia.codes`, fix per-deployment hostname

---

*Last updated: PostgreSQL timeout diagnosed and fixed. Pipeline should pass on next run.*
