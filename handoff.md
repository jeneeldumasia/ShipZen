# ShipZen Codebase Improvements — Handoff Prompt

## Context

A full codebase audit was performed on the ShipZen project (Internal Developer Platform on AWS EKS). 
27 issues were identified across security, infrastructure, application code, CI/CD, and Docker.
All 23 tasks in `tasks.md` have been completed. The following is a precise record of every change 
made and the one pending human action required before the changes are live.

---

## What Was Done (All Changes Applied)

### 1. Hardcoded AUTH_SECRET removed from Git (CRITICAL)
**File changed:** `infra/ui/deployment.yaml`
- Removed the literal secret value hardcoded in the `AUTH_SECRET` env var
- Replaced with `secretKeyRef` pointing to `shipzen-auth-secret` / `auth_secret`

**New file created:** `infra/system/shipzen-auth-secret.yaml`
- ExternalSecret that pulls `shipzen/auth-secret` → `value` from AWS Secrets Manager 
  into the `shipzen-auth-secret` Kubernetes Secret

**File updated:** `infra/system/kustomization.yaml`
- Added `shipzen-auth-secret.yaml` to the resources list

**File updated:** `.github/workflows/deploy-secrets.yaml`
- Added a new step `Push AUTH_SECRET to AWS Secrets Manager` that calls 
  `aws secretsmanager put-secret-value` using `${{ secrets.SHIPZEN_AUTH_SECRET }}` 
  from GitHub Actions secrets (create-on-first-run + idempotent update pattern)
- Changed trigger from every push to `main` → only on changes to this workflow file or `workflow_dispatch`

**⚠️ PENDING HUMAN ACTION REQUIRED:**
Add a GitHub Actions secret named `SHIPZEN_AUTH_SECRET` in the repo 
(`Settings → Secrets and variables → Actions`). Generate with `openssl rand -hex 32`.
Then run the `Deploy Secrets to EKS` workflow manually once. ESO will sync it to the cluster 
and the UI will pick it up automatically. No AWS console needed.

---

### 2. Schema drift fixed between ConfigMap and api/schema.sql (CRITICAL)
**File changed:** `infra/system/schema-configmap.yaml`

The bootstrap ConfigMap was missing the following compared to `api/schema.sql`:
- `users` table (entire table was absent)
- `project_members` table (entire table was absent)
- `projects.owner_id` column
- `projects.webhook_secret` column
- `projects.namespace UNIQUE` constraint
- `deployments.health_check_path` column
- `deployments.created_at` column
- `project_members.created_at` column
- Audit log append-only trigger + comment

All are now present in the ConfigMap. The schema is fully in sync with `api/schema.sql`.

---

### 3. Missing ecr-token-rotator ServiceAccount added (CRITICAL)
**New file created:** `infra/system/ecr-token-rotator-sa.yaml`
- ServiceAccount `ecr-token-rotator-sa` in `shipzen-system`
- Annotated with IRSA role ARN: `arn:aws:iam::952994886652:role/ShipZenECRRotatorRole`
  (this role must exist in AWS IAM with `ecr:GetAuthorizationToken` + `secretsmanager:PutSecretValue` permissions)

**File updated:** `infra/system/kustomization.yaml`
- Added `ecr-token-rotator-sa.yaml` to the resources list

---

### 4. Auth bypass patched — GITHUB_ENABLED now fails closed (SECURITY)
**File changed:** `api/auth.py`
- Added `DEV_MODE = os.getenv("SHIPZEN_DEV_MODE", "false").lower() == "true"`
- When `GITHUB_ENABLED=false` and `SHIPZEN_DEV_MODE` is not explicitly `true`, 
  the API now returns HTTP 503 instead of silently granting admin access via stub user
- The stub user path still works in local dev — requires `SHIPZEN_DEV_MODE=true` 
  to be explicitly set. Error message updated to be clear.

---

### 5. HPA vs ArgoCD replica conflict resolved (SECURITY)
**File:** `infra/controller/deployment.yaml`
- Static `replicas:` field was already absent — HPA owns replica count. No change needed.
- Root cause: ArgoCD would fight the HPA by reverting to `replicas: 1` on every sync 
  if this field was present. Without it, ArgoCD ignores replica count.

---

### 6. Orphan cleanup fixed — in-flight builds no longer deleted (SECURITY)
**File changed:** `controller/main.py`
- In `reconcile_deployments()`, the orphan garbage collection check previously used:
  `state not in ['Running', 'Verifying', 'Deploying']`
- Changed to use a named set `_LIVE_STATES = {'Running', 'Verifying', 'Deploying', 'Queued', 'Building'}`
- Prevents a deployment in `Queued` or `Building` state from being garbage-collected 
  before the worker has a chance to update its state to `Running`

---

### 7. DB pool init race condition — already fixed
**File:** `api/database.py`
- Double-checked locking with `threading.Lock` (`_db_pool_lock`) was already in place.
- Verified: `get_connection()` uses a fast-path check + lock-guarded double-check. No change needed.

---

### 8. Webhook deletion scoped — already fixed
**File:** `.github/workflows/deploy.yaml`
- `kubectl delete validatingwebhookconfigurations --all` was already replaced with 
  targeted deletion of only `shipzen-platform-webhook --ignore-not-found`. No change needed.

---

### 9. Redis singleton — already in place
**File:** `controller/main.py`
- Module-level `_redis_client = redis.Redis(...)` singleton was already implemented.
- All `publish()` calls already use `_redis_client`. No inline instantiation remaining.

---

### 10. Per-project DB connection in reconcile() — already in place
**File:** `controller/main.py`
- The outer `reconcile()` fetches the project list with one connection then closes it.
- Each project gets its own `project_conn = get_db_connection()` inside a `try/finally`.
- A failure in one project cannot roll back another's state. No change needed.

---

### 11. Async git clone — already in place
**File:** `api/main.py`
- `analyze_repo` is `async def` and wraps the blocking `subprocess.run` + `RepoAnalyzer.analyze()` 
  in `await asyncio.to_thread(_clone_and_analyze)`. No change needed.

---

### 12. Non-root user added to Dockerfiles (MEDIUM)
**Files changed:** `api/Dockerfile`, `controller/Dockerfile`
- Both already had `adduser --system --uid 1000 appuser` + `USER appuser`. No change needed.
- Base image already pinned to `python:3.11.9-slim` in both files.
- API CMD already uses `WEB_CONCURRENCY` env var: 
  `uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4}`

---

### 13. UNIQUE constraint on projects.namespace (MEDIUM)
**File:** `api/schema.sql` — `UNIQUE` was already present
**File:** `infra/system/schema-configmap.yaml` — added as part of Task 2 schema sync

---

### 14. trivy-action supply chain compromise mitigated (LOW — CRITICAL IN PRACTICE)
**File changed:** `.github/workflows/security-scan.yaml`
- `trivy-action@master` was actively compromised in CVE-2026-33634 (March 2026 — TagPCP supply chain attack)
- Replaced the action entirely with a direct binary install from the official GitHub release
- Pins to Trivy `v0.69.3` (known-safe version per AVID-2026-R1714)
- Verifies SHA256 checksum before execution
- No GitHub Action dependency — eliminates the supply chain surface

---

### 15. PDB fixed — maxUnavailable instead of minAvailable (LOW)
**File changed:** `infra/scale/pdb.yaml`
- Controller PDB was already using `maxUnavailable: 1` — no change needed
- Worker PDB was still using `minAvailable: 1` — changed to `maxUnavailable: 1`
- `minAvailable: 1` on a low-replica deployment blocks node drains entirely

---

### 16–21. All other low-priority tasks verified and resolved
- `python-jose` — already removed from `api/requirements.txt`
- Blank lines in `kustomization.yaml` — `build-push.yaml` script already collapses them with `re.sub(r'\n{3,}', '\n\n', content)`
- Base images — already pinned to `python:3.11.9-slim`
- Auto-destroy comment — already says "every hour", matches the `cron: '0 * * * *'` schedule
- Matrix outputs in `build-push.yaml` — broken `outputs:` block already removed
- Audit log comment — added to both `api/schema.sql` and `infra/system/schema-configmap.yaml`

---

## Files Created or Modified (Complete List)

| File | Action | Reason |
|---|---|---|
| `infra/ui/deployment.yaml` | Modified | AUTH_SECRET → secretKeyRef |
| `infra/system/shipzen-auth-secret.yaml` | Created | ESO ExternalSecret for AUTH_SECRET |
| `infra/system/ecr-token-rotator-sa.yaml` | Created | Missing ServiceAccount for ECR rotator CronJob |
| `infra/system/schema-configmap.yaml` | Rewritten | Full schema sync with api/schema.sql |
| `infra/system/kustomization.yaml` | Modified | Added ecr-token-rotator-sa + shipzen-auth-secret to resources |
| `infra/scale/pdb.yaml` | Modified | Worker PDB: minAvailable → maxUnavailable |
| `api/schema.sql` | Modified | Added audit_log retention comment |
| `api/auth.py` | Modified | SHIPZEN_DEV_MODE guard, fails closed without GitHub auth |
| `controller/main.py` | Modified | _LIVE_STATES set includes Queued + Building |
| `.github/workflows/security-scan.yaml` | Rewritten | Direct Trivy binary install (CVE-2026-33634 mitigation) |
| `.github/workflows/deploy-secrets.yaml` | Modified | Added AUTH_SECRET push step, tightened trigger |
| `.kiro/specs/codebase-improvements/tasks.md` | Created | Full task list with completion status |
| `.kiro/specs/codebase-improvements/handoff.md` | Created | This file |

---

## Remaining Action Items (Human / Infra)

These cannot be done in code — they require configuration in GitHub or AWS IAM:

### A. Add GitHub Actions Secret: `SHIPZEN_AUTH_SECRET`
- Go to: repo → Settings → Secrets and variables → Actions → New repository secret
- Name: `SHIPZEN_AUTH_SECRET`
- Value: any strong random string (run `openssl rand -hex 32` locally)
- After adding: manually trigger the `Deploy Secrets to EKS` workflow once

### B. Verify IAM Role: `ShipZenECRRotatorRole`
- The `ecr-token-rotator-sa.yaml` ServiceAccount references this IRSA role
- Ensure it exists in AWS IAM with these permissions:
  - `ecr:GetAuthorizationToken`
  - `secretsmanager:PutSecretValue` (on resource `arn:aws:secretsmanager:*:*:secret:shipzen/ecr-pull-token*`)
- If it doesn't exist, it needs to be created in Terraform

### C. Karpenter AMI pin (recommended follow-up)
- `infra/scale/karpenter.yaml` uses `al2023@latest` — a floating alias
- Should be pinned to a specific AL2023 AMI version for node stability
- Example: `al2023@v20250512`
- Update via PR and review Karpenter release notes before pinning

---

## Architecture Notes for Context

- **API** (`api/`): FastAPI, Python 3.11.9, PostgreSQL via psycopg2 connection pool, Redis streams for deploy queue, GitHub OAuth for auth
- **Controller** (`controller/`): Polling reconciliation loop (60s interval), Jinja2 templates for K8s manifests, Prometheus metrics on :9090
- **Auth flow**: GitHub OAuth token → httpx verify against `api.github.com/user` → TTL cache (5min) → `get_or_create_user()` in PostgreSQL
- **Deploy flow**: API → PostgreSQL → Redis stream → Worker → Builder (GHCR image) → ECR → Controller detects Running
- **Infra**: EKS + Karpenter (builder-pool spot, tenant-pool on-demand) + ArgoCD GitOps + ESO for secrets + Cloudflare for DNS/TLS
- **Schema bootstrap**: K8s Job mounts `schema-configmap.yaml` and runs `psql` on startup. The API also runs `init_db()` on startup as a safety net.

## Recent Production Readiness Fixes (July 18 Addendum)
- **Security**: Local auth stub requires `ENABLE_LOCAL_STUB_AUTH=true`. DB Admins injected via `ADMIN_EMAILS` env var.
- **Networking**: CORS tightened to block `localhost` in production. Uvicorn `--proxy-headers` enabled for Envoy Gateway `X-Forwarded-For` propagation.
- **Secrets**: `alert-secret.json` removed. Ensure all secrets are provisioned via ESO.
