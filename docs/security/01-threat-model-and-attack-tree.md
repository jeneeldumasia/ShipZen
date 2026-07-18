# Platform Threat Model & Attack Tree

## 1. Trust Boundaries
ShipZen enforces strict trust boundaries across its architecture:
- **Untrusted (Internet):** Incoming traffic via Cloudflare/ALB to Envoy Gateway.
- **Semi-Trusted (Tenant Apps):** User-supplied code executing inside dynamically provisioned Namespaces.
- **Semi-Trusted (Builder Pool):** The `shipzen-build` namespace executing untrusted source code and `Dockerfile` configurations.
- **Trusted (Control Plane):** The Controller, Worker, PostgreSQL database, and Redis Streams inside `shipzen-system`.

## 2. Attack Tree Analysis

The following tree outlines potential attack vectors and the implemented mitigations designed in previous phases.

### A. Tenant Privilege Escalation & Lateral Movement
- **Goal:** Tenant application compromises the host node or laterally moves to another tenant/control plane.
- **Attack Vector A1:** Container breakout to underlying host.
  - *Mitigation:* Restricted Pod Security Standards (PSS) enforce `runAsNonRoot`, disable privilege escalation, and drop all capabilities. `RuntimeDefault` seccomp profiles are applied.
- **Attack Vector A2:** Network probing to control plane or other tenants.
  - *Mitigation:* Default-deny `NetworkPolicy` isolates the namespace. Egress is strictly explicitly defined (DNS + specific external APIs).
- **Attack Vector A3:** Cloud Metadata (IMDS) credential theft.
  - *Mitigation:* NetworkPolicy strictly drops egress to `169.254.169.254/32`.

### B. Malicious Build Execution
- **Goal:** Malicious code executes during the CI build phase to steal credentials or pivot into the cluster.
- **Attack Vector B1:** Executing arbitrary code during `kaniko` or `pack` build.
  - *Mitigation:* Builder pods are completely isolated in `shipzen-build` namespace with identical NetworkPolicies and PSS hardening.
  - *Mitigation:* NodePool taints ensure builders run on isolated instances (Spot).
- **Attack Vector B2:** Accessing long-lived registry credentials.
  - *Mitigation:* IRSA (IAM Roles for Service Accounts) provides short-lived AWS STS tokens to access ECR. No long-lived Kubernetes Secrets exist.

### C. Secret Exfiltration
- **Goal:** Attacker steals API keys or database passwords.
- **Attack Vector C1:** Reading `Secret` objects in Kubernetes.
  - *Mitigation:* RBAC restricts tenant runner roles. External Secrets Operator (ESO) fetches secrets just-in-time from AWS Secrets Manager.
- **Attack Vector C2:** Secrets printed in build logs.
  - *Mitigation:* ESO mounts secrets directly into `envFrom`. Cloud Native Buildpacks restrict secret binding during image creation.

### D. API & Authentication Compromise
- **Goal:** Attacker bypasses authentication to mutate platform state or exhaust API resources.
- **Attack Vector D1:** Bypassing GitHub OAuth using development stubs.
  - *Mitigation:* Explicit `ENABLE_LOCAL_STUB_AUTH=true` environment variable mandated; falls closed to 503 if not set in production.
- **Attack Vector D2:** Proxy IP Spoofing for Rate Limit Evasion.
  - *Mitigation:* Uvicorn `--proxy-headers` configuration enforces validation of `X-Forwarded-For` from the Envoy Gateway, dropping spoofed headers.
