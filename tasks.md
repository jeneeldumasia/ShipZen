# ShipZen Codebase Improvements — Task List

## Critical (🔴)

- [x] 1. Fix hardcoded AUTH_SECRET in infra/ui/deployment.yaml — moved to ExternalSecret (shipzen-auth-secret.yaml)
- [x] 2. Fix schema drift — infra/system/schema-configmap.yaml now matches api/schema.sql fully
- [x] 3. Add missing ecr-token-rotator-sa ServiceAccount manifest (ecr-token-rotator-sa.yaml)

## Security (🟠 High)

- [x] 4. Fix GITHUB_ENABLED auth bypass — now fails closed unless SHIPZEN_DEV_MODE=true is explicit
- [x] 5. Fix HPA vs ArgoCD replica conflict — static replicas field already removed from controller Deployment
- [x] 6. Fix orphan cleanup deleting in-flight Queued/Building deployments — added to _LIVE_STATES set
- [x] 7. Fix DB pool lazy-init race condition — double-checked locking with threading.Lock already in place

## Medium (🟡)

- [x] 8. Fix blanket kubectl delete webhookconfigurations — already fixed in deploy.yaml (targets by name)
- [x] 9. Fix Redis connection-per-event in controller — module-level _redis_client singleton already in place
- [x] 10. Fix shared DB connection across projects in reconcile() — per-project connection already implemented
- [x] 11. Fix blocking git clone in analyze_repo route — asyncio.to_thread already in place
- [x] 12. Add USER directive to both Dockerfiles — non-root appuser with UID 1000 added
- [x] 13. Add UNIQUE constraint on projects.namespace — already in api/schema.sql, added to ConfigMap

## Low (🟢)

- [x] 14. Replace trivy-action@master with direct binary install — rewrote security-scan.yaml (CVE-2026-33634)
- [x] 15. Fix controller PDB maxUnavailable — already done; also fixed worker PDB
- [x] 16. Remove unused python-jose dependency — already removed from api/requirements.txt
- [x] 17. Add --workers flag to Uvicorn — done via WEB_CONCURRENCY env var in api/Dockerfile
- [x] 18. Clean up blank lines in kustomization.yaml — re.sub collapse already in build-push.yaml script
- [x] 19. Pin base images in Dockerfiles — both pinned to python:3.11.9-slim
- [x] 20. Fix auto-destroy.yaml comment — already correct (says "every hour")
- [x] 21. Fix matrix job outputs in build-push.yaml — outputs block already removed
- [x] 23. Add audit_logs retention comment — added to both schema.sql and schema-configmap.yaml

## Remaining

- [ ] 22. Align infra/system/kustomization.yaml — verify all new files are listed (ecr-token-rotator-sa, shipzen-auth-secret)
      STATUS: Done — both added in kustomization.yaml during Task 3

## Production Readiness (Completed)

- [x] PR-1. Secured Auth Bypass — Replaced DEV mode environment check with strict `ENABLE_LOCAL_STUB_AUTH=true`
- [x] PR-2. Removed hardcoded DB Admins — Replaced with `ADMIN_EMAILS` environment variable
- [x] PR-3. Fixed DB transaction boundaries for user creation TOCTOU race condition
- [x] PR-4. Network Proxy Hardening — Appended `--proxy-headers` to Uvicorn and parsed `X-Forwarded-For`
- [x] PR-5. Secret Management Cleanup — Deleted `alert-secret.json` and added `*-secret.json` to `.gitignore`
- [x] PR-6. CORS Hardening — Blocked `localhost:3000` access unless `ENVIRONMENT=development`
