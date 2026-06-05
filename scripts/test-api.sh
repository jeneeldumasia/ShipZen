#!/usr/bin/env bash
# DeployHub API smoke test
# Run after: docker compose up --build
# Requires: curl, jq

set -euo pipefail

BASE="http://localhost:8000"
PASS=0
FAIL=0

green() { echo -e "\033[32m✓ $*\033[0m"; }
red()   { echo -e "\033[31m✗ $*\033[0m"; }

check() {
  local label="$1"
  local expected_status="$2"
  local actual_status="$3"
  local body="$4"
  if [ "$actual_status" = "$expected_status" ]; then
    green "$label (HTTP $actual_status)"
    PASS=$((PASS+1))
  else
    red "$label — expected HTTP $expected_status, got $actual_status"
    echo "  Body: $body"
    FAIL=$((FAIL+1))
  fi
}

echo ""
echo "══════════════════════════════════════════"
echo "  DeployHub API Smoke Test"
echo "══════════════════════════════════════════"
echo ""

# ── 1. Health check ───────────────────────────────────────────────────────────
echo "── Health ──────────────────────────────"
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/healthz")
BODY=$(cat /tmp/dh_body)
check "GET /healthz" "200" "$RESP" "$BODY"

# ── 2. List projects (empty) ──────────────────────────────────────────────────
echo ""
echo "── Projects ────────────────────────────"
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/projects")
BODY=$(cat /tmp/dh_body)
check "GET /projects (empty list)" "200" "$RESP" "$BODY"

# ── 3. Create project — valid ─────────────────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" -X POST "$BASE/projects" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-app","namespace":"my-app-ns"}')
BODY=$(cat /tmp/dh_body)
check "POST /projects (valid)" "201" "$RESP" "$BODY"

PROJECT_ID=$(echo "$BODY" | jq -r '.id // empty')
if [ -z "$PROJECT_ID" ]; then
  red "Could not extract project_id from response — aborting remaining tests"
  echo "Body was: $BODY"
  exit 1
fi
echo "  project_id = $PROJECT_ID"

# ── 4. Create project — invalid namespace ─────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" -X POST "$BASE/projects" \
  -H "Content-Type: application/json" \
  -d '{"name":"bad","namespace":"Bad_Namespace"}')
BODY=$(cat /tmp/dh_body)
check "POST /projects (invalid namespace → 422)" "422" "$RESP" "$BODY"

# ── 5. Create project — namespace too short ───────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" -X POST "$BASE/projects" \
  -H "Content-Type: application/json" \
  -d '{"name":"bad","namespace":"ab"}')
BODY=$(cat /tmp/dh_body)
check "POST /projects (namespace too short → 422)" "422" "$RESP" "$BODY"

# ── 6. Get project ────────────────────────────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/projects/$PROJECT_ID")
BODY=$(cat /tmp/dh_body)
check "GET /projects/{id}" "200" "$RESP" "$BODY"

# ── 7. Get project — not found ────────────────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/projects/does-not-exist")
BODY=$(cat /tmp/dh_body)
check "GET /projects/{id} (not found → 404)" "404" "$RESP" "$BODY"

# ── 8. Create deployment — valid ──────────────────────────────────────────────
echo ""
echo "── Deployments ─────────────────────────"
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" \
  -X POST "$BASE/projects/$PROJECT_ID/deployments" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/jeneeldumasia/DeployHub",
    "image_name": "123456789012.dkr.ecr.us-east-1.amazonaws.com/deployhub-builds:latest",
    "replicas": 1,
    "port": 8080
  }')
BODY=$(cat /tmp/dh_body)
check "POST /deployments (valid → 202)" "202" "$RESP" "$BODY"

DEPLOYMENT_ID=$(echo "$BODY" | jq -r '.deployment_id // empty')
if [ -z "$DEPLOYMENT_ID" ]; then
  red "Could not extract deployment_id"
  echo "Body was: $BODY"
else
  echo "  deployment_id = $DEPLOYMENT_ID"
fi

# ── 9. Create deployment — bad repo_url ───────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" \
  -X POST "$BASE/projects/$PROJECT_ID/deployments" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "file:///etc/passwd",
    "image_name": "some-image:latest"
  }')
BODY=$(cat /tmp/dh_body)
check "POST /deployments (file:// URL → 422)" "422" "$RESP" "$BODY"

# ── 10. Create deployment — bad replicas ──────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" \
  -X POST "$BASE/projects/$PROJECT_ID/deployments" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/jeneeldumasia/DeployHub",
    "image_name": "some-image:latest",
    "replicas": 999
  }')
BODY=$(cat /tmp/dh_body)
check "POST /deployments (replicas=999 → 422)" "422" "$RESP" "$BODY"

# ── 11. List deployments ──────────────────────────────────────────────────────
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/projects/$PROJECT_ID/deployments")
BODY=$(cat /tmp/dh_body)
check "GET /deployments (list)" "200" "$RESP" "$BODY"
COUNT=$(echo "$BODY" | jq 'length // 0')
echo "  deployments in list: $COUNT"

# ── 12. Get deployment ────────────────────────────────────────────────────────
if [ -n "$DEPLOYMENT_ID" ]; then
  RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" \
    "$BASE/projects/$PROJECT_ID/deployments/$DEPLOYMENT_ID")
  BODY=$(cat /tmp/dh_body)
  check "GET /deployments/{id}" "200" "$RESP" "$BODY"
  STATE=$(echo "$BODY" | jq -r '.state // empty')
  echo "  deployment state: $STATE"
fi

# ── 13. List builds (empty) ───────────────────────────────────────────────────
echo ""
echo "── Builds ──────────────────────────────"
if [ -n "$DEPLOYMENT_ID" ]; then
  RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" \
    "$BASE/projects/$PROJECT_ID/deployments/$DEPLOYMENT_ID/builds")
  BODY=$(cat /tmp/dh_body)
  check "GET /builds (empty list)" "200" "$RESP" "$BODY"
fi

# ── 14. Audit log ─────────────────────────────────────────────────────────────
echo ""
echo "── Audit ───────────────────────────────"
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/projects/$PROJECT_ID/audit")
BODY=$(cat /tmp/dh_body)
check "GET /audit" "200" "$RESP" "$BODY"
AUDIT_COUNT=$(echo "$BODY" | jq 'length // 0')
echo "  audit entries: $AUDIT_COUNT"

# ── 15. Redis enqueue check ───────────────────────────────────────────────────
echo ""
echo "── Redis ───────────────────────────────"
STREAM_LEN=$(docker compose exec -T redis redis-cli xlen deploy_stream 2>/dev/null || echo "?")
echo "  deploy_stream length: $STREAM_LEN"
if [ "$STREAM_LEN" = "1" ]; then
  green "Redis stream has 1 message (deployment enqueued correctly)"
  PASS=$((PASS+1))
elif [ "$STREAM_LEN" = "?" ]; then
  echo "  (could not check Redis — run manually: docker compose exec redis redis-cli xlen deploy_stream)"
else
  red "Expected 1 message in stream, got $STREAM_LEN"
  FAIL=$((FAIL+1))
fi

# ── 16. Delete project ────────────────────────────────────────────────────────
echo ""
echo "── Cleanup ─────────────────────────────"
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" -X DELETE "$BASE/projects/$PROJECT_ID")
BODY=$(cat /tmp/dh_body)
check "DELETE /projects/{id} (→ 202 Terminating)" "202" "$RESP" "$BODY"

# Confirm status is now Terminating
RESP=$(curl -s -o /tmp/dh_body -w "%{http_code}" "$BASE/projects/$PROJECT_ID")
BODY=$(cat /tmp/dh_body)
STATUS=$(echo "$BODY" | jq -r '.status // empty')
if [ "$STATUS" = "Terminating" ]; then
  green "Project status is Terminating after DELETE"
  PASS=$((PASS+1))
else
  red "Expected status=Terminating after DELETE, got '$STATUS'"
  FAIL=$((FAIL+1))
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "══════════════════════════════════════════"
echo ""

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
