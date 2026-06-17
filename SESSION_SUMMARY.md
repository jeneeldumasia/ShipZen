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

**Last run: IN PROGRESS / SUCCESS**

**Issues Fixed This Session:**
- **NLB 10-minute Timeout:** Caused by multiple chained race conditions and API changes.
- **ArgoCD App Race Conditions:** `deployhub-platform` ArgoCD app was syncing before operators (AWS ALB Controller, Envoy, Cert Manager) were ready. Added strict `depends_on` chains in `argocd.tf`.
- **Envoy Gateway CRD Version Mismatch:** `EnvoyProxy` apiVersion was using `config.gateway.envoyproxy.io/v1alpha1` instead of `gateway.envoyproxy.io/v1alpha1`, causing the `deployhub-platform` ArgoCD app to fail its sync, which meant the `Gateway` resource was never deployed and the AWS NLB was never requested.
- **Webhook Race Conditions:** `aws-load-balancer-controller` webhook wasn't ready before `kube-prometheus-stack` tried to deploy, causing `no endpoints available for service` errors. Added `time_sleep.wait_for_alb_webhook` dependencies.
- **Kyverno Pod Security Standard Blocks:** Kyverno's strict cluster policies blocked the `prometheus-node-exporter` DaemonSet (`disallow-host-namespaces`, `disallow-host-path`). Disabled `nodeExporter` in the Helm chart to allow deployment to proceed safely in a managed EKS environment.
- **DNS Resolution Errors:** `kubectl` hung locally due to stale EKS cluster endpoints. Resolved by running `aws eks update-kubeconfig`.

---

## Known Issues & Warnings

**Non-blocking warnings (safe to ignore):**
- `resolve_conflicts` deprecated on `aws_eks_addon` — this is from the upstream `terraform-aws-modules/eks` module, not our code. Will be fixed when the module releases a new version.

**Still outstanding (see `docs/TASKS.md` for full backlog):**

| ID | Priority | Issue |
|----|----------|-------|
| OBS-1 | P1 | Per-pod monitoring not wired up (PodMonitor per tenant namespace) |
| OBS-2 | P1 | Grafana dashboards reference non-existent metrics — need rewriting |
| OBS-3 | P1 | Missing `deployhub_deployment_success_total`, `_failure_total`, `build_duration_seconds` metrics |
| FEAT-3 | P2 | GitHub Webhook → auto-deploy not implemented |
| SEC-1 | P2 | Re-enable `node-exporter` by creating a fine-grained Kyverno `PolicyException`. |

---

## Next Session

1. **Confirm pipeline passes fully** with the updated EnvoyProxy API version.
2. Implement Kyverno `PolicyException` for `node-exporter`.
3. Proceed with further application development or monitoring fixes.

---

*Last updated: 2026-06-17. Resolved NLB timeouts, Envoy Gateway API version mismatch, webhook race conditions, and Kyverno PSS blocks.*
