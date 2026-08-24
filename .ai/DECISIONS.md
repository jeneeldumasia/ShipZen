# Architectural Decisions

## CI/CD Infrastructure Updates (Strict GitOps)
* **Decision**: All AWS infrastructure changes MUST go through the `.github/workflows/deploy.yaml` GitHub Actions pipeline.
* **Reason**: To enforce GitOps and prevent configuration drift.
* **What should NOT be changed**: Do not run `terraform apply` locally or use the `aws` CLI locally to create resources.

## Tenant vs. System Security Isolation
* **Decision**: Kyverno enforces strict pod security (Baseline/Restricted) on tenant namespaces (like `default` and `shipzen-build`), but the `observability` and `kube-system` namespaces are excluded via Webhook Configuration.
* **Reason**: Tools like Prometheus `node-exporter` fundamentally require privileged access (`hostNetwork`, `hostPath`) to monitor the underlying EC2 nodes. Exempting the namespace from Kyverno is an industry-standard way to permit core system functions while relentlessly locking down tenant workloads.
* **What should NOT be changed**: Do not remove the `observability` exclusion from `security.tf` unless replacing it with a hyper-specific `PolicyException` CRD for `node-exporter`. 

## Infrastructure Persistence & Cost Control
* **Decision**: All data storage (Prometheus, Grafana databases) use `gp2` PVCs to prevent data loss on pod restart. Lifecycle policies aggressively cull old data (30 days for S3 logs, EKS CloudWatch logs, and untagged ECR images).
* **Reason**: Production environments require stability and persistence, but portfolio/startup projects require strict cost control mechanisms to prevent infinite storage bills.
* **What should NOT be changed**: Do not disable the lifecycle policies in `main.tf` or remove the persistence configurations in `monitoring.tf`.

## Append-Only Audit Logs
* **Decision**: The `audit_logs` table in PostgreSQL uses database triggers to enforce append-only rules.
* **Reason**: Ensures security audit compliance by completely blocking `UPDATE` or `DELETE` operations at the database engine level.
* **What should NOT be changed**: Do not remove or bypass the `trg_audit_logs_append_only` trigger in `schema.sql`.
