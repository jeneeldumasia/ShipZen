# Platform Hardening Report

This report summarizes the definitive security controls configured and enforced globally across ShipZen.

## 1. Workload Isolation
- **Restricted Pod Security Standards (PSS):** Enforced natively on all dynamically generated tenant namespaces and the static `shipzen-build` namespace via `pod-security.kubernetes.io/enforce: restricted`.
- **Security Contexts:**
  - `runAsNonRoot: true` and `runAsUser: 1000` mandated.
  - `allowPrivilegeEscalation: false` applied.
  - `capabilities: drop: ["ALL"]` enforced.
  - `seccompProfile: type: RuntimeDefault` applied to prevent custom syscalls.

## 2. Network Hardening
- **Default Deny Ingress/Egress:** Implemented via Kubernetes NetworkPolicies inside every tenant namespace.
- **IMDS Block:** The AWS EC2 Instance Metadata Service (`169.254.169.254/32`) is explicitly blacklisted in the egress policy to prevent SSRF-driven IAM credential theft.
- **Internal Subnet Block:** The `10.0.0.0/8`, `172.16.0.0/12`, and `192.168.0.0/16` RFC1918 blocks are excluded from Egress rules, strictly preventing lateral network exploration.
- **TLS Termination:** Handled safely by Envoy Gateway; wildcard TLS certificates secure data-in-transit.

## 3. Secret Management & Identity
- **External Secrets Operator (ESO):** Replaced native K8s secrets with dynamic syncs from AWS Secrets Manager.
- **IRSA (IAM Roles for Service Accounts):** The cluster utilizes strictly scoped IAM roles bound via OIDC to specific ServiceAccounts (e.g., `external-secrets-sa`, `builder-sa`). Long-lived keys are entirely eradicated.

## 4. Build Security
- **Rootless Kaniko:** Dockerfile fallback mechanism utilizes the `executor` binary to achieve container builds without disabling the OCI process sandbox or requiring Docker-in-Docker (DinD).
- **S3 Log Streaming:** Logs are piped natively to S3, averting local disk saturation attacks (Denial of Service).

## 5. API & Application Hardening
- **Authentication Strictness:** Stub authentication is strictly gated behind `ENABLE_LOCAL_STUB_AUTH=true`, effectively neutering accidental exposure.
- **Rate Limit Proxy Awareness:** `X-Forwarded-For` propagation is strictly enforced to prevent external rate-limit evasion and prevent global blocks caused by Envoy IP overlap.
- **CORS Hardening:** `localhost:3000` cross-origin requests are blocked universally unless `ENVIRONMENT=development`.
- **Database Consistency:** Explicit transaction boundaries (`conn.commit()`) wrap critical paths (like User provisioning) to prevent Time-of-Check to Time-of-Use (TOCTOU) race conditions.
