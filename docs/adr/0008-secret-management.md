# ADR 0008: Secret Management

**Status:** ACCEPTED
**Context:** Applications require sensitive configurations (API keys, DB credentials).
**Decision:** Centralized secret management via AWS Secrets Manager. External Secrets Operator (ESO) will sync these into per-tenant Kubernetes Secrets. Secrets injected via ESO `envFrom` or `volumeMount` are permitted — only hardcoded plaintext values are forbidden. 
**Consequences:** 
- Secrets are never hardcoded or stored in PostgreSQL.
- Provides a centralized audit trail via AWS.
- All legacy local secret stubs (e.g., `alert-secret.json`) are strictly forbidden from version control and must be managed via ESO.
**Conflict Resolution Policy:** Secrets passed as plaintext environment variables, embedded in Git, or stored in dummy local JSON files will be rejected.
