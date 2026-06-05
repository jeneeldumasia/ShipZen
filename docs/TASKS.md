# DeployHub — Task Backlog

> Canonical source of upcoming work. Ordered by priority within each section.
> Format: `[ ]` = not started, `[~]` = in progress, `[x]` = done

---

## Domain & DNS Architecture

**Domain:** `jeneeldumasia.codes` (owned)

**DNS layout:**

| Hostname | Purpose |
|----------|---------|
| `deployhub.jeneeldumasia.codes` | DeployHub UI + API (CNAME → NLB) |
| `api.deployhub.jeneeldumasia.codes` | API server direct access |
| `grafana.deployhub.jeneeldumasia.codes` | Grafana dashboard |
| `*.deployhub.jeneeldumasia.codes` | Wildcard — all user app deployments |
| `{dep-id}.{project}.deployhub.jeneeldumasia.codes` | Per-deployment URL (e.g. `a1b2c3d4.my-app.deployhub.jeneeldumasia.codes`) |

**Setup:**
- In your domain registrar / Route53, create a CNAME: `*.deployhub.jeneeldumasia.codes` → NLB DNS name (output from `terraform output nlb_dns_name` after deploy)
- cert-manager issues a wildcard cert for `*.deployhub.jeneeldumasia.codes` via DNS-01 challenge on Route53
- The double-wildcard `*.{project}.deployhub.jeneeldumasia.codes` requires a separate cert or a SAN cert covering both levels — Let's Encrypt supports this via DNS-01

**Everywhere `deployhub.io` appears in the codebase, replace with `deployhub.jeneeldumasia.codes`:**
- `gateway/gateway.yaml` — gateway hostname
- `controller/templates/app-deployment.yaml.j2` — HTTPRoute hostname
- `terraform/main.tf` — any hardcoded domain references
- `ui/.env.local` — `NEXT_PUBLIC_APP_DOMAIN`

---

## 🔴 P0 — Blocking / Correctness

### AUTH-1: OIDC Authentication & Multi-User Support
**Why:** The API has zero authentication. Any user can read or delete any other user's projects. `user_id` is hardcoded to `"api"` in all audit logs. This is a critical security gap before any public exposure.

**Approach:** OAuth2 Authorization Code Flow with PKCE — industry standard for browser-based apps.

- **Identity Provider:** Auth0 (free tier covers this project). Alternatively AWS Cognito if staying in the AWS ecosystem.
- **API (`api/main.py`):**
  - Add `python-jose[cryptography]` + `httpx` dependencies
  - `get_current_user()` dependency: extracts Bearer token from `Authorization` header, validates signature against Auth0 JWKS endpoint, returns `user_id = token["sub"]`
  - All project/deployment endpoints inject `current_user` — queries filter by `owner_id`
  - Public endpoints: `GET /healthz` only
- **Schema (`api/schema.sql`):** Add `owner_id VARCHAR(255) NOT NULL` to `projects` table. Index on `owner_id`.
- **UI (`ui/`):**
  - Install `next-auth@5` (App Router compatible)
  - Configure Auth0 provider in `auth.ts`
  - Wrap layout in `SessionProvider`
  - `middleware.ts` — redirect unauthenticated users to `/login`
  - Pass `session.accessToken` as `Authorization: Bearer` on all API calls
  - Show user avatar + name in sidebar footer; replace "Connected" indicator
- **Admin role:** `https://deployhub.jeneeldumasia.codes/roles` claim in JWT. Admins see all projects across all users.
- **Env vars needed:** `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_AUDIENCE` — add to `infra/api/deployment.yaml` as Secret refs and `ui` deployment.

---

### DNS-1: Fix Per-Deployment Wildcard Routing + Domain Update
**Why:** Two bugs combined:
1. All deployments in a project share `{project_name}.deployhub.jeneeldumasia.codes` — duplicate HTTPRoutes cause undefined routing behaviour
2. The domain is still `deployhub.io` throughout the codebase

**Fix:**

Update `controller/templates/app-deployment.yaml.j2` hostname to:
```
{{ deployment_id[:8] }}.{{ project_name }}.deployhub.jeneeldumasia.codes
```

Update `gateway/gateway.yaml` listeners to:
```yaml
hostname: "*.deployhub.jeneeldumasia.codes"
```

Add `NEXT_PUBLIC_APP_DOMAIN=deployhub.jeneeldumasia.codes` env var to the UI so the deployment detail page can construct live URLs client-side.

---

### INFRA-1: cert-manager + Wildcard TLS Certificate
**Why:** `gateway/gateway.yaml` references `deployhub-tls-cert` Secret which is never created. The HTTPS listener will fail to start, breaking all tenant traffic.

**Fix:**
- Add to `terraform/operators.tf`:
  ```hcl
  resource "helm_release" "cert_manager" {
    name       = "cert-manager"
    repository = "https://charts.jetstack.io"
    chart      = "cert-manager"
    version    = "v1.15.1"
    namespace  = "cert-manager"
    create_namespace = true
    set { name = "installCRDs", value = "true" }
    depends_on = [module.eks]
  }
  ```
- Add Route53 IRSA role for DNS-01 challenge (needs `route53:ChangeResourceRecordSets` on the hosted zone)
- Add to `infra/system/`:
  - `clusterissuer.yaml` — Let's Encrypt production issuer using Route53 DNS-01
  - `certificate.yaml` — wildcard cert for `*.deployhub.jeneeldumasia.codes` stored as `deployhub-tls-cert` in `deployhub-system` namespace
- Add `terraform output route53_hosted_zone_id` so the ClusterIssuer can reference it

---

### BUG-1: Projects Page Broken
**Why:** `/projects` redirects to `/`, making the sidebar nav item feel broken. `PageHeader` receives JSX as `description` but types it as `string`.

**Fix:**
- Remove `app/projects/page.tsx` redirect — replace with a proper projects grid page (card-based layout, one card per project showing name, namespace, status, deployment count, last activity)
- Fix `PageHeader` component: change `description?: string` to `description?: React.ReactNode`
- Fix sidebar active detection: "Projects" should be active on all `/projects/*` routes, not just exact `/projects`

---

### BUG-2: Deploy Form Submit Wiring
**Why:** The deploy form in `/projects/[id]/deployments/new` has `handleSubmit` attached via `onClick` on a button outside the `<form>` tag — the `form` attribute reference is stale. Pressing Enter doesn't submit. Form validation doesn't run.

**Fix:** Wrap all form fields in a single `<form onSubmit={handleSubmit}>` and make the submit button `type="submit"` inside it. Remove the `onClick` workaround.

---

### INFRA-3: Karpenter Installation via Terraform
**Why:** `infra/scale/karpenter.yaml` defines NodePools and EC2NodeClasses but Karpenter itself is never installed. Without it, the CRDs don't exist and ArgoCD will fail to sync the entire `infra/scale/` directory.

**Fix:** Add to `terraform/operators.tf`:
```hcl
resource "helm_release" "karpenter" {
  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "0.37.0"
  namespace  = "karpenter"
  create_namespace = true

  set { name = "settings.clusterName",     value = module.eks.cluster_name }
  set { name = "settings.interruptionQueue", value = aws_sqs_queue.karpenter.name }
  set { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn",
        value = module.irsa_karpenter.iam_role_arn }

  depends_on = [module.eks]
}
```
Also add the required SQS queue for interruption handling and the Karpenter IRSA role.

---

## 🟠 P1 — High Value Features

### OBS-1: Per-Pod Monitoring
**Why:** No visibility into what tenant pods are doing. Platform operators and users are blind once a deployment is "Running".

**What to add:**
- In `controller/templates/app-deployment.yaml.j2`, add pod annotations:
  ```yaml
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "{{ port | default(8080) }}"
    prometheus.io/path: "/metrics"
  ```
- In `controller/templates/tenant.yaml.j2`, add a `PodMonitor` resource that discovers all pods in the namespace with label `app`
- kube-state-metrics (included in kube-prometheus-stack) already provides `kube_pod_container_resource_requests`, `kube_pod_status_ready`, restart counts
- In the UI, add a "Metrics" tab on the deployment detail page with 3 sparkline charts: CPU usage, memory usage, restart count — fetched via the Grafana HTTP API

---

### OBS-2: Preconfigured Grafana Dashboards (Rewritten)
**Why:** Existing dashboards reference non-existent metrics. They need to be rebuilt against real PromQL.

**4 dashboards to build in `observability/dashboards/grafana-dashboards.yaml`:**

**1. Platform Health (`platform-health.json`)**
- Queue depth: `deployhub_queue_depth`
- DLQ depth: `deployhub_dlq_depth`
- Retry rate: `rate(deployhub_retry_total_total[5m])`
- Reconciliation duration: `deployhub_reconciliation_duration_seconds`
- Drift events: `rate(deployhub_drift_total_total[5m])`

**2. Build Performance (`build-performance.json`)**
- Build duration p50/p95 (requires OBS-3 to add the histogram)
- Build success vs failure over time
- Active builder pods: `kube_deployment_status_replicas_ready{deployment="deployhub-builder"}`

**3. Per-Project Resource Usage (`project-resources.json`)**
- CPU usage per namespace: `sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace)`
- Memory per namespace: `sum(container_memory_working_set_bytes) by (namespace)`
- Quota saturation: `kube_resourcequota{type="used"} / kube_resourcequota{type="hard"}`
- All filtered by label `deployhub.io/tenant="true"`

**4. Per-Deployment Pod Health (`pod-health.json`)**
- Pod ready status: `kube_pod_status_ready`
- Restart count: `kube_pod_container_status_restarts_total`
- CPU/memory per pod over time
- Template variable: `$namespace` + `$deployment` so users can drill into their own app

**Grafana embed in UI:**
- Add `/observability` page to the UI with Grafana panels embedded as iframes
- Use Grafana's `kiosk` mode + anonymous auth (internal network only)
- Link "View Metrics" button from the deployment detail page to a pre-filtered per-deployment dashboard URL
- Add `grafana.deployhub.jeneeldumasia.codes` HTTPRoute in `infra/system/`

---

### OBS-3: Missing SLO Metrics Instrumentation
**Why:** Three SLO recording rules were removed because the metrics don't exist.

**Add to `worker/metrics.py`:**
```python
deployhub_deployment_success_total = Counter(
    'deployhub_deployment_success_total',
    'Total successful deployments reaching Running state'
)
deployhub_deployment_failure_total = Counter(
    'deployhub_deployment_failure_total',
    'Total deployments that ended in Failed or DLQ state'
)
```
Increment in `worker/main.py` when state transitions to `Running` (success) or `DLQ` (failure).

**Add to `builder/main.py`:**
```python
deployhub_build_duration_seconds = Histogram(
    'deployhub_build_duration_seconds',
    'Build duration from clone to push',
    buckets=[30, 60, 120, 300, 600, 900]
)
```
Observe with `time.time() - build_start` after `process.communicate()` returns.

Re-enable the 3 removed rules in `observability/slos.yaml` after instrumenting.

---

### UI-1: Dark / Light Mode Toggle
**Approach:**
- `npm install next-themes`
- Add `<ThemeProvider attribute="class" defaultTheme="system" enableSystem>` in `layout.tsx`
- Set `darkMode: "class"` in `tailwind.config.ts`
- Rewrite all colour tokens in `globals.css` as CSS variables:
  ```css
  :root { --bg: #fafafa; --card: #ffffff; --border: #e4e4e7; --text: #18181b; --muted: #71717a; }
  .dark { --bg: #09090b; --card: #111113; --border: #27272a; --text: #fafafa;  --muted: #a1a1aa; }
  ```
- Add Sun/Moon toggle button in Sidebar footer
- Persist to `localStorage` via `next-themes`

---

### UI-2: Visual Design Overhaul — Cohesive Palette
**Problem:** Near-black sidebar (#0f1117) against cold off-white (#f8fafc) with clashing pastel status badges = incoherent.

**New palette — zinc/violet (Linear-inspired):**

| Token | Light | Dark |
|-------|-------|------|
| Background | `#fafafa` | `#09090b` |
| Card | `#ffffff` | `#111113` |
| Border | `#e4e4e7` | `#27272a` |
| Text primary | `#18181b` | `#fafafa` |
| Text muted | `#71717a` | `#a1a1aa` |
| Sidebar bg | `#18181b` | `#0c0c0e` |
| Accent | `#7c3aed` | `#8b5cf6` |
| Accent hover | `#6d28d9` | `#7c3aed` |

**Status colours (semantic, bold):**

| State | Colour | Hex |
|-------|--------|-----|
| Running | Green | `#22c55e` |
| Building | Blue + pulse | `#3b82f6` |
| Deploying | Cyan + pulse | `#06b6d4` |
| Verifying | Violet + pulse | `#8b5cf6` |
| Queued | Zinc | `#a1a1aa` |
| Failed | Red | `#ef4444` |
| Retry | Amber | `#f59e0b` |
| DLQ | Red bold | `#dc2626` |

**Also:**
- Sidebar border changes from `#1e2130` to `#27272a` (same token as card borders — unified)
- Remove the jarring dual-tone split; sidebar and content area should feel like one surface
- All rounded corners `rounded-xl` → `rounded-lg` (flatter, more modern)
- Table rows: remove alternating backgrounds; use hover + subtle left border on active rows instead

---

### UI-3: Deployment Live URL
After DNS-1 is fixed, the deployment detail page shows a prominent live banner when `state === "Running"`:
```
● Live   https://a1b2c3d4.my-project.deployhub.jeneeldumasia.codes   [Open ↗] [Copy]
```
- URL constructed as `{deployment_id.slice(0,8)}.{project_name}.deployhub.jeneeldumasia.codes`
- Read `NEXT_PUBLIC_APP_DOMAIN` env var so the domain is not hardcoded in UI code
- Copy button uses `navigator.clipboard.writeText()`
- Only shown when `state === "Running"` — hidden otherwise

---

### UI-4: Build Log Viewer
**Why:** Build logs go to S3 but are inaccessible from the UI. The only way to debug a failed build is to manually fetch from S3.

**API endpoint:** `GET /projects/{id}/deployments/{dep_id}/builds/{build_id}/logs`
- Calls `boto3.client('s3').generate_presigned_url()` with `ExpiresIn=900` (15 min)
- Returns `{ "url": "<presigned_s3_url>" }`

**UI:** On the Build History table row, replace the raw S3 URI with a "Logs" button:
- Click opens a modal/drawer with the log rendered in a dark terminal-style `<pre>` block
- Fetches the pre-signed URL client-side and streams the text
- Syntax: ANSI escape codes stripped, newlines preserved, auto-scroll to bottom

---

### UI-5: Loading Skeletons
Add `loading.tsx` alongside each page for the Next.js App Router streaming pattern:
- `app/loading.tsx` — 4 metric tiles + 5 table row skeletons
- `app/projects/[id]/loading.tsx` — header skeleton + 4 mini stats + table skeleton
- `app/projects/[id]/deployments/[depId]/loading.tsx` — pipeline tracker skeleton + detail grid skeleton

Use `animate-pulse` on `bg-zinc-100 dark:bg-zinc-800` rounded placeholders.

---

## 🟡 P2 — Quality of Life

### FEAT-1: One-Click Redeploy
- Add "Redeploy" button on deployment detail page (only when `state === "Running"` or `"Failed"`)
- Calls `POST /projects/{id}/deployments` with the same `repo_url`, `branch`, `port`
- Button shows spinner while submitting, then navigates to the new deployment page

---

### FEAT-2: Environment Variables UI
Add an "Env Vars" tab to the project detail page:
- `GET /projects/{id}/env` — returns list of secret key names (not values) from AWS Secrets Manager path `deployhub/{project_name}/`
- `PUT /projects/{id}/env` — writes/updates a key/value pair
- `DELETE /projects/{id}/env/{key}` — deletes a key
- UI: key-value table with add/delete inline; values masked with "Reveal" toggle
- ESO refreshes the synced K8s Secret within the configured `refreshInterval` (1h)

---

### FEAT-3: GitHub Webhook → Auto-Deploy
- `POST /webhooks/github/{project_id}` endpoint
- Validates `X-Hub-Signature-256` HMAC against a per-project webhook secret stored in the DB
- Triggers a new deployment on `push` events to the configured branch
- UI: "Webhooks" section on project settings page — shows webhook URL + secret, copy button

---

### FEAT-4: Activity Feed on Dashboard
- Replace the projects-only dashboard with a split view: project list on the left, global activity feed on the right
- Feed shows last 20 audit events across all the user's projects: "John deployed X", "Project Y created", "Build failed for Z"
- Polling refresh every 30s (not real-time — websockets are a P3 scope)

---

### FEAT-5: `deployhub.yaml` in Builder
Repo root config file that builder reads before invoking `pack`:
```yaml
# deployhub.yaml
port: 3000
runtime: nodejs        # hints to pack builder selection
health_check_path: /health
```
- `port` overrides the API-level port
- `health_check_path` used for K8s readiness probe (currently hardcoded to `/`)
- `runtime` passed as `--buildpack` flag to `pack` to skip auto-detection

---

### INFRA-2: Rate Limiting on the API
Add `slowapi` middleware to `api/main.py`:
- Keyed by `user_id` (from JWT) when authenticated, IP address otherwise
- `POST /projects` — 10 req/min
- `POST /projects/{id}/deployments` — 5 req/min (prevent triggering unbounded builds)
- All `GET` endpoints — 100 req/min
- Return `429 Too Many Requests` with `Retry-After` header

---

### OBS-5: Grafana Accessible from DeployHub UI
- Add `grafana.deployhub.jeneeldumasia.codes` HTTPRoute in `infra/system/`
- In `terraform/monitoring.tf`, set `grafana.grafana.ini."server".domain = "grafana.deployhub.jeneeldumasia.codes"` and `root_url`
- Add `/observability` page in the UI:
  - Embeds Grafana's "Platform Health" dashboard via iframe (anonymous viewer access, internal only)
  - "View in Grafana" link opens the full dashboard in a new tab
- On deployment detail page, add "View Metrics →" link that deep-links to the per-deployment pod health dashboard with `$namespace` and `$deployment` pre-filled as query params

---

## 🔵 P3 — Nice to Have

### UI-6: Toast Notifications
- `npm install sonner`
- Replace all `alert()` calls and silent redirects with toast messages
- Success toasts: "Project created", "Deployment submitted", "Project deleted"
- Error toasts: API error message content, 5s auto-dismiss
- Position: bottom-right

---

### UI-7: Keyboard Shortcuts
- `N` — New project (from dashboard)
- `D` — Deploy (from project page)
- `R` — Redeploy (from deployment detail, when applicable)
- `Cmd/Ctrl+K` — Command palette: fuzzy search across projects and deployments, navigate instantly

---

### OBS-4: Alertmanager Routing (Slack + PagerDuty)
- `platform-alerts.yaml` rules exist but Alertmanager has no routing config
- Add `alertmanager-config.yaml` ConfigMap to `infra/system/`:
  - `severity: warning` → Slack `#deployhub-alerts`
  - `severity: critical` → PagerDuty + Slack
  - `severity: high` → Slack only, 5min repeat interval
- Webhook URLs stored in AWS Secrets Manager, synced via ESO

---

### SEC-1: Network Policy for API Server
The API server pod can reach any pod in the cluster — no egress restriction.

Add `infra/api/networkpolicy.yaml`:
```yaml
egress:
  - ports: [5432]  # PostgreSQL only
    to: [deployhub-system postgres pods]
  - ports: [6379]  # Redis only
    to: [deployhub-system redis pods]
  - ports: [443]   # AWS APIs (S3, Secrets Manager, ECR) via NAT
    to: [0.0.0.0/0 except RFC1918]
```

---

### SEC-2: ECR Image Scanning Gate
ECR `scan_on_push = true` is already configured. Add a post-build check:
- After `process.communicate()` succeeds in `builder/main.py`, call `ecr.describe_image_scan_findings()`
- Poll until scan status is `COMPLETE` (up to 60s)
- If any `CRITICAL` finding exists, set state to `Failed` with error "Image scan: CRITICAL vulnerability found in {package}"
- Configurable threshold via `IMAGE_SCAN_FAIL_ON` env var (`CRITICAL` default, `HIGH` for stricter gates)

---

### FEAT-6: WebSocket Live Logs
Replace the 5s polling `AutoRefresh` on the deployment detail page with a WebSocket connection:
- `GET /ws/projects/{id}/deployments/{dep_id}/status` — streams state transition events
- UI transitions the pipeline tracker in real-time without full page refreshes
- Requires `websockets` dependency in FastAPI (`app.add_websocket_route`)

---

## ✅ Already Done (for reference)

- [x] Destroy workflow fixed (Karpenter nodes, NLB ENIs, ArgoCD race, finalizers, orphaned SGs)
- [x] Auto-destroy deadman switch (4h uptime limit)
- [x] `apply_manifests()` now uses K8s Python client (was no-op)
- [x] Builder: Kaniko removed, always uses `pack --publish` (rootless-compatible)
- [x] Worker: DB reconnection logic, schema conflict removed
- [x] Worker: idempotency guard expanded to BUILDING + DEPLOYING states
- [x] Worker: retry `queued_at` reset on re-queue
- [x] API: user inputs repo URL only — image URI auto-generated as `<ecr_repo>:<deployment_id>`
- [x] API: replicas removed from user input — platform-controlled
- [x] API: CORS middleware added
- [x] HTTP→HTTPS 301 redirect on gateway
- [x] Tenant RBAC: `secrets` removed from tenant-runner Role
- [x] Karpenter builder-pool taint + toleration on builder pods
- [x] Karpenter tenant-pool taint + toleration on tenant app pods (node isolation)
- [x] ECR pull secret per tenant namespace via ESO ExternalSecret
- [x] ServiceMonitors for worker (8000), controller (9090), API (8000)
- [x] Schema bootstrap Job (ArgoCD PostSync hook, idempotent)
- [x] Terraform: Redis, PostgreSQL, KEDA, ESO, ALB Controller, kube-prometheus-stack
- [x] GitHub Actions IAM scoped to minimum permissions + main branch only
- [x] `deployhub_drift_total` Gauge → Counter (rate() alerts now work)
- [x] SLO recording rules cleaned up (removed 3 rules for non-existent metrics)
- [x] `deployhub-db-credentials`, `deployhub-s3-config`, `deployhub-ecr-config` K8s Secrets via Terraform
- [x] Controller: ECR_REGISTRY env var wired into tenant namespace template
- [x] UI: dark sidebar layout, custom Tailwind design tokens
- [x] UI: StatusBadge with animated pulsing dots per state
- [x] UI: MetricCard, EmptyState, PageHeader, cn() utility
- [x] UI: deploy form — repo URL + branch only, Advanced toggle for port
- [x] UI: deployment detail — visual pipeline tracker (Queued→Building→Deploying→Verifying→Running)
- [x] UI: auto-refresh every 4s while deployment is in-progress
