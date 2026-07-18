# Issues and Resolutions

This document tracks recently encountered infrastructure, deployment, and UI issues along with their resolutions.

## Infrastructure & CI/CD

### 1. Manual Pod Restarts Required for GitOps Deployments
- **Issue:** ArgoCD was not detecting new Docker images pushed by the GitHub Actions pipeline because the deployment manifest was hardcoded to use the `latest` tag. The Git manifests themselves were never changing, meaning ArgoCD saw the cluster state as "Synced" and didn't trigger a rollout.
- **Resolution:** Modified `.github/workflows/build-push.yaml` to include an automated tagging step. The pipeline now extracts the `sha-xxxxxx` tag from the build, uses a Python script to rewrite `newTag` in `infra/kustomization.yaml`, and automatically commits the change back to the repository using a retry-rebase loop to avoid parallel matrix merge conflicts. ArgoCD now detects the commit and auto-syncs.

### 2. Builder Pods Stuck in "Building" (KEDA Autoscaling Failure)
- **Issue:** KEDA was failing to scale the `shipzen-builder` pods from `0` to `1`. The logs showed an error attempting to mount `shipzen-db-credentials` and `shipzen-s3-config`. Terraform created these secrets in `shipzen-system`, but the builder runs in the isolated `shipzen-build` namespace, triggering a cross-namespace secret mount failure.
- **Resolution:** Updated `terraform/postgres.tf` to provision duplicate `kubernetes_secret` resources injected directly into the `shipzen-build` namespace. For immediate recovery, used `kubectl` to manually copy the secrets over, unblocking the stuck pods instantly.

### 3. Terraform "gavinbunney/kubectl" 500 Internal Server Error
- **Issue:** The GitHub Actions infrastructure pipeline was crashing during `terraform init` with a 500 API rate-limit error when fetching the legacy `gavinbunney/kubectl` provider checksums.
- **Resolution:** Investigated the Terraform configuration and confirmed that `kubectl_manifest` was completely unused (the project relies on `local-exec` bash provisioners for kubectl commands). Removed the unused legacy provider from `main.tf` entirely, allowing the pipeline to bypass the dependency block.

## Frontend & Observability

### 4. Grafana Dashboards Not Found (404 Error)
- **Issue:** Clicking "View Metrics" in the UI redirected to `/d/pod-health`, but Grafana showed a "Dashboard not found" error. The dashboard config map existed in `observability/dashboards` but was never applied by ArgoCD. Additionally, the dashboard JSON models were missing explicit `uid` fields, causing Grafana to auto-generate random UIDs instead.
- **Resolution:** Injected `"uid": "pod-health"` (and similar UIDs) into the JSON payloads in `grafana-dashboards.yaml`. Copied the ConfigMap into `infra/system/grafana-dashboards.yaml` and added it to the ArgoCD kustomization list so it automatically deploys to the cluster.

### 5. Invisible Brand Logo in Dark Mode
- **Issue:** The ShipZen rocket logo was hardcoded with `text-white` over `bg-brand`. In dark mode, `bg-brand` flips to white, making the logo completely invisible.
- **Resolution:** Replaced all instances of `text-white` placed over `bg-brand` with the semantic `text-canvas-bg` utility. This ensures the text color elegantly inverts to pure black when dark mode switches the background to white.

### 6. Default Vercel Favicon
- **Issue:** The website browser tab was displaying the default boilerplate Next.js/Vercel triangle logo.
- **Resolution:** Generated a new, minimalist white rocket icon on a solid black background using the image generator tool. Replaced `favicon.ico` with the new `icon.png` in `ui/src/app` to apply the ShipZen branding to the browser tab.


### 7. Builder Pods Not Scaling from Zero (Stuck on Building)
- **Issue:** Deployments would get permanently stuck on the "Building" phase because the builder pods failed to scale up from zero. This was caused by two intertwined KEDA issues:
  1. KEDA's `redis-streams` scaler requires the `builder_group` consumer group to already exist in Redis. If the builder pods are at 0, they can't create it, causing a `NOGROUP` error in KEDA.
  2. The ScaledObject was using `pendingEntriesCount: "1"`, which only scales based on messages currently being processed (in the Pending Entries List). Without consumers, the PEL remains 0 forever.
- **Resolution:** Modified `worker/main.py` to ensure the consumer group is initialized upon worker startup. Updated `infra/builder/scaledobject.yaml` to use `lagCount: "1"` and `activationLagCount: "0"` instead, enabling KEDA to correctly measure the queue backlog and scale to zero.

## Backend & Architecture Resolved Issues

### 8. GitHub Actions OIDC Failure on Repository Rename
* **Issue:** After renaming the GitHub repository from `DeployHub` to `ShipZen`, the deployment pipeline failed with `Not authorized to perform sts:AssumeRoleWithWebIdentity`. GitHub was sending OIDC tokens as `ShipZen`, but the AWS IAM Role's trust policy still expected `DeployHub`.
* **Resolution:** Manually accessed the AWS IAM Console, located the `DeployHub-AA-SuperRole`, and updated the Trust Relationship condition to expect `repo:jeneeldumasia/ShipZen:ref:refs/heads/main`.
* **Did it work?** Yes. The pipeline immediately successfully authenticated.

### 9. HCP Terraform "No Valid Credentials" on Remote Run
* **Issue:** When running `terraform plan` on a newly created `shipzen-prod` HCP Terraform workspace, the pipeline crashed saying it couldn't reach the AWS EC2 metadata endpoint. This occurred because new workspaces default to "Remote Execution" mode, meaning the code ran on HashiCorp servers that lacked AWS credentials, rather than the GitHub runner.
* **Resolution:** Changed the "Execution Mode" in the HCP Terraform Workspace settings from "Remote" to "Local".
* **Did it work?** Yes. The execution stayed on the GitHub Actions runner which had temporary AWS credentials injected via OIDC.

### 10. Envoy Gateway CRD Version Mismatch
* **Issue:** The `shipzen-platform` ArgoCD app failed to sync because it was using an outdated API version for the Envoy Gateway (`config.gateway.envoyproxy.io/v1alpha1`). Because it failed, the AWS NLB was never requested.
* **Resolution:** Updated the manifests to use the correct API version: `gateway.envoyproxy.io/v1alpha1`.
* **Did it work?** Yes. ArgoCD successfully synced the gateway and provisioned the Network Load Balancer.

### 11. Webhook Race Conditions & NLB Timeouts
* **Issue:** The `aws-load-balancer-controller` webhook wasn't ready before `kube-prometheus-stack` tried to deploy, resulting in "no endpoints available for service" errors and causing the NLB provisioning to time out after 10 minutes.
* **Resolution:** Added strict `depends_on` chains and `time_sleep.wait_for_alb_webhook` in the Terraform configuration to ensure webhooks were fully ready before dependent helm charts deployed.
* **Did it work?** Yes. The dependency chaining eliminated the race condition.

### 12. Kyverno Pod Security Standard Blocks
* **Issue:** Kyverno's strict cluster policies blocked the `prometheus-node-exporter` DaemonSet (`disallow-host-namespaces`, `disallow-host-path`).
* **Resolution:** Disabled the `nodeExporter` component in the Helm chart entirely to allow deployment to proceed safely in a managed EKS environment while maintaining compliance.
* **Did it work?** Yes.

### 13. UI Docker Build Cache Errors
* **Issue:** Docker builds for the Next.js UI were failing due to missing cache directories during the build context copy phase.
* **Resolution:** Modified the `Dockerfile` to explicitly create the `public/` directory prior to the build context copy.
* **Did it work?** Yes. Builds now complete without cache permission errors.

### 14. Cloudflare Orphaned DNS Records
* **Issue:** Tearing down the platform left stale `*.shipzen` and `shipzen` CNAME records in Cloudflare, leading to clutter and potential routing conflicts on subsequent runs.
* **Resolution:** Added a dedicated Cloudflare DNS cleanup script utilizing the Cloudflare API to the `destroy` pipeline.
* **Did it work?** Yes. DNS records are cleanly wiped on teardown.

### 15. Karpenter Autoscaling Runaway Costs
* **Issue:** The Karpenter node pools were scaling too aggressively, spinning up expensive instances that threatened to consume the AWS free-tier/student credits too quickly.
* **Resolution:** Implemented hard resource limits on the Karpenter node pools to keep scaling restricted to minimal, cost-effective boundaries.
* **Did it work?** Yes.

### 16. Database Connection Leaks in API
* **Issue:** Previously, the FastAPI application did not use a connection pool, risking DB connection exhaustion. 
* **Resolution:** Replaced raw `psycopg2.connect()` calls with a robust `psycopg2.pool.ThreadedConnectionPool` and `PooledConnectionWrapper` to ensure connections are properly recycled.
* **Did it work?** Yes. The API now safely handles concurrent requests without leaking connections.

### 17. Controller Cannot Update Existing Deployments
* **Issue:** The Controller's reconciliation loop was returning a 409 Conflict when a user deployed a newer image tag for an existing project because it only tried to create resources.
* **Resolution:** Added explicit `patch_namespaced_deployment` and `patch_namespaced_service` fallback logic in `apply_manifests()` whenever the `create_from_yaml` throws a 409 ApiException.
* **Did it work?** Yes. Rolling updates now trigger properly upon redeployment.

### 18. Environment Variables Path Mismatch
* **Issue:** A mismatch between the API storing secrets at `shipzen/{project_name}/` and the Controller attempting to read from `shipzen/{project_name}/{deployment_uuid}` meant environments variables never injected.
* **Resolution:** Aligned the paths. The `app-deployment.yaml.j2` manifest was updated to extract data directly from `shipzen/{{ project_name }}/`.
* **Did it work?** Yes.

### 19. ECR Pull Token Not Rotating
* **Issue:** The Kubernetes cluster used a static AWS token to pull images from ECR, which would expire every 12 hours, eventually breaking pod restarts.
* **Resolution:** Integrated External Secrets Operator (ESO) `ECRAuthorizationToken` generator in `tenant.yaml.j2` to dynamically rotate and inject fresh ECR tokens every hour.
* **Did it work?** Yes. 

### 20. Redis Streams Lack End-to-End Guarantees
* **Issue:** Build tasks could be permanently lost if the Builder pod crashed mid-build because it didn't track pending/un-acked messages.
* **Resolution:** Implemented a robust `recover_pending_messages` loop using Redis `xpending_range` and `xclaim` in the Builder loop to sweep and re-claim stalled messages.
* **Did it work?** Yes. Build tasks are now guaranteed to be picked up by another pod.

### 21. Builder Ignores Branch Parameter
* **Issue:** The API accepted a `branch` parameter, but the Worker dropped the field when moving the message from the `deploy_stream` to the `builder_queue`. As a result, the Builder always checked out the `main` branch.
* **Resolution:** Explicitly added `"branch": data.get("branch", "main")` to the `handoff_to_builder` dictionary payload in `worker/main.py`.
* **Did it work?** Yes. Deployments now respect specific branches.

### 22. Dark Mode Legibility on Active Navbar Link
* **Issue:** In the Next.js UI, the active sidebar navigation item was using white text on a white background when in dark mode.
* **Resolution:** Appended `dark:text-black` to the `.nav-item.active` class in `globals.css` so the text shifts to black when the active glassmorphism background is bright white.
* **Did it work?** Yes. The navigation is now highly legible in both dark and light modes.

## Technical Debt & Pending Architecture Improvements

### 23. Multi-Tenant Webhook Branch Cross-Contamination
* **Issue:** The `projects` database schema lacks explicit `repo_url` and `branch` configuration. GitHub webhooks blindly trigger deployments across all projects sharing a repository using whatever branch was just pushed, cross-contaminating staging and production environments.
* **Proposed Resolution:** Migrate the `projects` table to explicitly store `repo_url` and `branch`. The webhook receiver (`api/main.py`) must be updated to filter matching projects against the pushed branch.

### 24. Admin Role Revocation Cache Delay
* **Issue:** Caching the fully resolved `User` object (including role) in `api/auth.py` eliminates database overhead but causes a 5-minute propagation delay when a user's role is updated via the `/admin/users/{user_id}/role` API. Demoted admins retain access until their cache TTL expires.
* **Proposed Resolution:** Implement a global reverse-mapping dictionary (`user_id -> list[token_hashes]`) so the admin endpoint can explicitly evict tokens from the cache upon role demotion.

## Production Readiness (July 18)

### 25. Authentication Stub Vulnerability
* **Issue:** The `stub-token` logic relied on a fragile `ENVIRONMENT != "development"` and `NODE_ENV !== "production"` check which could fail open if misconfigured.
* **Resolution:** Replaced the environmental checks with a strict, explicit opt-in `ENABLE_LOCAL_STUB_AUTH=true`.

### 26. Hardcoded Admin Escalation
* **Issue:** Initial DB migrations hardcoded specific developer emails to automatically gain `admin` privileges upon login.
* **Resolution:** Replaced the hardcoded lists with an `ADMIN_EMAILS` environment variable parameter for secure bootstrapping.

### 27. Transaction Boundaries & TOCTOU in User Creation
* **Issue:** The `get_or_create_user` method suffered from Time-of-Check to Time-of-Use race conditions with implicit psycopg2 auto-commit behaviors on connection pool exit.
* **Resolution:** Implemented explicit `conn.commit()` and `conn.rollback()` handling tightly wrapped around the SQL execution blocks.

### 28. Proxy Rate-Limit Exhaustion
* **Issue:** The `slowapi` rate limiter fell back to `get_remote_address()`, which resolved to the Envoy Gateway internal IP, causing global rate limits to block all users.
* **Resolution:** Appended `--proxy-headers` to Uvicorn and explicitly parsed `X-Forwarded-For` in `_user_id_or_ip`.
