# DeployHub — Session Summary & Checkpoint

> **ATTENTION FOR NEXT SESSION:** Read this entire document before writing any code or making architectural changes.

---

## 🏆 Session 1 — Greenfield Implementation
Built the entire DeployHub backend from scratch across 15 phases:
- **PostgreSQL** as source of truth (`api/schema.sql`)
- **Controller** — reconciliation loop, drift detection, Kubernetes namespace provisioning
- **Worker** — Redis Streams consumer, state machine, retry/DLQ logic
- **Builder** — Cloud Native Buildpacks, S3 log streaming
- **Terraform** — VPC, EKS, IAM, OIDC, S3, ArgoCD GitOps bootstrap
- **Observability** — Prometheus rules, Grafana dashboards, SLOs, alerts
- **Gateway** — Envoy Gateway with wildcard TLS, tenant HTTPRoutes
- **Multi-tenancy** — Restricted PSS, NetworkPolicy, ResourceQuota, RBAC per namespace

---

## 🔧 Session 2 — Fault Analysis & Fixes

### Context
- Student account, AWS credits (~$134 remaining). Infra torn down after every session.
- `t3.medium` nodes intentional — `t2.micro` caused lag.
- Cost: ~$0.35–0.40/hr base (EKS flat fee + 2x t3.medium + NAT gateway).

### Key fixes (27 faults addressed)
- `apply_manifests()` was a no-op → now uses K8s Python client
- `deployhub_drift_total` was a Gauge → changed to Counter so `rate()` alerts work
- Worker DB connection had no reconnect logic → `_get_conn()` auto-reconnects
- Worker `_ensure_table()` created a 4-column schema conflicting with canonical schema → removed
- Builder: Kaniko removed (incompatible with `runAsNonRoot`) → always uses `pack --publish`
- Tenant RBAC removed `secrets` from Role
- All services raise on missing `DATABASE_URL`
- Controller `autocommit=False` with explicit commit/rollback
- Destroy workflow rewritten — fixes leftover resources on teardown (Karpenter nodes, NLB ENIs, orphaned SGs, ArgoCD race condition)
- Auto-destroy deadman switch (`auto-destroy.yaml`) — triggers after 4h uptime

---

## 🏗️ Session 3 — Infrastructure Completion, API Server & UI

### Terraform — all operators now installed on `terraform apply`
| File | What |
|------|------|
| `terraform/redis.tf` | Bitnami Redis, single master, no persistence |
| `terraform/postgres.tf` | Bitnami PostgreSQL, 10Gi PVC, writes `deployhub-db-credentials` + `deployhub-s3-config` + `deployhub-ecr-config` K8s Secrets |
| `terraform/operators.tf` | KEDA, ESO, AWS Load Balancer Controller (IRSA), ClusterSecretStore with dynamic region+account ID |
| `terraform/monitoring.tf` | kube-prometheus-stack, Grafana sidecar dashboards enabled, no persistence |
| `terraform/main.tf` | ECR repo, S3 encryption, `aws_caller_identity`, 5 outputs, GitHub Actions IAM scoped to minimum permissions |
| `terraform/variables.tf` | `pg_password`, `grafana_password` variables |

### infra/ — all missing Deployment manifests created
| Path | What |
|------|------|
| `infra/kustomization.yaml` | Top-level ArgoCD entry point |
| `infra/system/` | `deployhub-system` namespace, schema bootstrap Job (PostSync ArgoCD hook), ServiceMonitors for all services |
| `infra/controller/` | Deployment, ServiceAccount, ClusterRole/Binding, kustomization |
| `infra/worker/` | Deployment, ServiceAccount, kustomization |
| `infra/api/` | Deployment, Service, ServiceAccount, kustomization |
| `infra/builder/deployment.yaml` | Toleration for `deployhub.io/dedicated=builder` node taint, env vars fixed |

### API Server (`api/`) — Phase 16 complete
Full FastAPI server with 10 endpoints. Key design decisions:
- **User inputs repo URL only** — platform auto-generates image URI as `<ecr_repo>:<deployment_id>`
- **No replicas field** — platform-controlled; Karpenter/KEDA own scaling
- Port optional (defaults to 8080), in Advanced section
- CORS middleware for `localhost:3000`
- Audit logging on all state-changing operations

### Infrastructure bug fixes completed
| # | Fix |
|---|-----|
| #5.4 | Karpenter `tenant-pool` now has `deployhub.io/dedicated=tenant:NoSchedule` taint. Tenant pods have matching toleration. Builder pods have builder taint toleration. Node pools fully isolated. |
| #6.1 | `observability/slos.yaml` rewritten — removed 3 rules referencing non-existent metrics, kept only rules backed by real instrumentation |
| #8.8 | `controller/templates/tenant.yaml.j2` creates `ecr-pull-secret` ExternalSecret per namespace via ESO. App template uses `imagePullSecrets`. Controller passes `ECR_REGISTRY` env var to template. |

### Local testing confirmed
- `docker compose up --build` → postgres + redis + api at `localhost:8000`
- All 13 API smoke tests pass
- Deployment API: user submits only repo URL, image_uri auto-generated as `local/deployhub-builds:<deployment_id>`

---

## 🎨 Session 3 (continued) — UI Modernization

### Design overhaul
Complete redesign from a plain white table UI to a professional dark-sidebar IDP dashboard.

**Design system (`tailwind.config.ts` + `globals.css`):**
- Custom colour tokens: `sidebar.*`, `canvas.*`, `brand.*`, `status.*`
- Google Fonts: Inter (UI) + JetBrains Mono (code/IDs)
- Component utility classes: `.card`, `.input`, `.btn-primary`, `.btn-ghost`, `.btn-danger`, `.nav-item`, `.metric-tile`, `.table-row-hover`
- Custom animations: `fade-in`, `slide-in`, `pulse-slow`
- Custom scrollbar styling

**New/rewritten components:**
| Component | What |
|-----------|------|
| `Sidebar.tsx` | Fixed dark sidebar (w-60), logo with glow, nav items with active state, connection status footer |
| `StatusBadge.tsx` | Pill badges with animated pulsing dots per state (replaces flat coloured spans) |
| `MetricCard.tsx` | Stat tiles with icon, colour, and trend support |
| `EmptyState.tsx` | Centred empty states with icon, title, description, CTA |
| `PageHeader.tsx` | Consistent page header with title, description, and action slot |
| `cn.ts` | `clsx` + `tailwind-merge` utility |

**Pages redesigned:**
| Page | Changes |
|------|---------|
| `/` Dashboard | Dark sidebar layout, metric cards with icons, project table with hover-reveal actions, folder icons per row |
| `/projects/new` | Card form with icon header, auto-generated namespace preview pill, cleaner field layout |
| `/projects/[id]` | Status badge inline, 4 metric cards, deployment table with repo icon, hover-reveal View link |
| `/projects/[id]/deployments/new` | Repo URL + branch only visible; Advanced toggle reveals port; animated pipeline preview showing what will happen |
| `/projects/[id]/deployments/[depId]` | **Visual pipeline tracker** (Queued → Building → Deploying → Verifying → Running) with active/done/failed states; 4 detail cards; build history table; audit log table |

**Removed:** `Nav.tsx` (replaced by `Sidebar.tsx`)

All pages compile clean. Dev server at `http://localhost:3000`.

---

## 🌐 Domain Decision
**Domain:** `jeneeldumasia.codes` (owned)
**Platform URL:** `deployhub.jeneeldumasia.codes` → CNAME to NLB DNS name
**Tenant app URLs:** `{dep-id}.{project}.deployhub.jeneeldumasia.codes` (per-deployment, unique)
**Grafana:** `grafana.deployhub.jeneeldumasia.codes`

All references to `deployhub.io` in the codebase need to be replaced with `deployhub.jeneeldumasia.codes`. This is tracked as task DNS-1 in `docs/TASKS.md`.

cert-manager with Let's Encrypt DNS-01 (Route53) required for the wildcard cert `*.deployhub.jeneeldumasia.codes`. Tracked as INFRA-1.

---

## ⚠️ Outstanding Issues

Full task backlog with detailed specs is in **`docs/TASKS.md`**.

Summary by priority:

**P0 — Blocking:**
- `AUTH-1` — No authentication. `user_id` hardcoded. Any user can touch any project. Fix: Auth0 OIDC + `next-auth` + FastAPI JWT middleware + `owner_id` on projects table.
- `DNS-1` — All deployments in a project share one hostname. Routing breaks with >1 deployment. Fix: per-deployment subdomain `{dep-id}.{project}.deployhub.jeneeldumasia.codes`. Also replaces all `deployhub.io` references.
- `INFRA-1` — `deployhub-tls-cert` Secret never created. HTTPS listener silently fails. Fix: cert-manager + Let's Encrypt DNS-01 via Route53.
- `BUG-1` — `/projects` redirect makes sidebar nav broken. `PageHeader` type error.
- `BUG-2` — Deploy form submit wiring uses `onClick` instead of proper `onSubmit`.
- `INFRA-3` — Karpenter CRDs used but Karpenter never installed via Terraform.

**P1 — High value:**
- `OBS-1` — Per-pod monitoring (PodMonitor per tenant namespace, metrics tab in UI)
- `OBS-2` — Grafana dashboards rewritten with real PromQL (4 dashboards)
- `OBS-3` — Missing SLO metrics (add to worker + builder, re-enable 3 SLO rules)
- `OBS-5` — Grafana accessible from DeployHub UI at `grafana.deployhub.jeneeldumasia.codes`
- `UI-1` — Dark/light mode toggle (`next-themes`, CSS variables)
- `UI-2` — Design overhaul (zinc/violet palette, unified sidebar/content surface)
- `UI-3` — Live deployment URL display when Running
- `UI-4` — Build log viewer (presigned S3 URL → terminal modal)
- `UI-5` — Loading skeletons

**P2+ — Quality of life and nice-to-haves:** see `docs/TASKS.md`

---

## 🚀 Next Session Action Items

1. **BUG-1 + BUG-2** — Fix the broken projects page and deploy form wiring (30 min)
2. **UI-1 + UI-2** — Dark mode + design overhaul (these should be done together)
3. **AUTH-1** — OIDC auth is the most impactful unfinished piece
4. **DNS-1 + INFRA-1** — Domain update + cert-manager (required before `terraform apply` works end-to-end)
5. **INFRA-3** — Karpenter install (required before any auto-scaling works)
6. **OBS-2 + OBS-3** — Fix Grafana dashboards + add missing metrics
7. **`terraform apply`** — Full end-to-end cluster test on `jeneeldumasia.codes`

---

*Last updated: Session 3 — Infrastructure, API, UI modernization, domain finalized as `jeneeldumasia.codes`.*
