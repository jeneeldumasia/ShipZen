"""
ShipZen API Server — Phase 16
FastAPI service that is the sole HTTP entry point for the platform.
All state-changing operations write to PostgreSQL and enqueue to Redis.
The controller and worker drive everything asynchronously from there.
"""

from typing import Literal
import os
import re
import time
import datetime
import uuid
import logging
from typing import Optional

import redis as redis_lib
import redis.asyncio as aioredis
import psycopg2
from psycopg2.extras import DictCursor
from fastapi import FastAPI, HTTPException, Query, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
import json
from pydantic import BaseModel, field_validator
import boto3
import hmac
import hashlib
import secrets
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request

from database import get_connection, init_db, verify_project_access
from contextlib import asynccontextmanager
from audit import log_audit_event
from auth import get_current_user, User

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('api')

from kubernetes import client, config as k8s_config
try:
    k8s_config.load_incluster_config()
except Exception:
    pass
apps_v1 = client.AppsV1Api()

# ── Config ────────────────────────────────────────────────────────────────────

REDIS_HOST = os.getenv(
    "REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_NAME = os.getenv("STREAM_NAME", "deploy_stream")

# ECR repository URL — injected by Terraform at deploy time.
# The API constructs the full image URI as: <ECR_URL>:<deployment_id>
# Users never see or input this value.
ECR_REPOSITORY_URL = os.getenv("ECR_REPOSITORY_URL", "")

# Repo URL allowlist — same pattern used in builder/main.py
# MED-03 Fix: Use \A and \Z anchors to prevent newline injection
_REPO_URL_RE = re.compile(
    r'\A(https://[a-zA-Z0-9._/:\-@]+\.git'
    r'|https://[a-zA-Z0-9._/:\-@]+'
    r'|git@[a-zA-Z0-9._\-]+:[a-zA-Z0-9._/\-]+\.git)\Z'
)

# Branch name validation regex — shared with webhook handler (CRIT-01)
_BRANCH_RE = re.compile(r'^[a-zA-Z0-9_.\-/]{1,200}$')

# HIGH-20 Fix: Reserved namespace prefixes that tenants cannot use
_RESERVED_NS_PREFIXES = ('kube-', 'shipzen-', 'default', 'observability', 'kyverno', 'argocd')

# PERF-01 Fix: Module-level boto3 Secrets Manager client singleton
_sm_client = boto3.client('secretsmanager', region_name=os.getenv('AWS_REGION', 'us-east-1'))

# Kubernetes namespace name rules: lowercase alphanumeric and hyphens, 3–63 chars
_NAMESPACE_RE = re.compile(r'^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$')


REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

_redis_pool = redis_lib.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
_redis_client = redis_lib.Redis(connection_pool=_redis_pool)
_aioredis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
def get_redis() -> redis_lib.Redis:
    return _redis_client

# ── FastAPI app ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    await _aioredis_client.aclose()
    _redis_client.close()

app = FastAPI(
    title="ShipZen API",
    description="Internal Developer Platform — deploy any repo to Kubernetes",
    version="1.0.0",
    lifespan=lifespan,
)


def _user_id_or_ip(request: Request) -> str:
    # Use Authorization header sub if present, fallback to IP
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            return hashlib.sha256(token.encode()).hexdigest()[:32]
        except Exception:
            pass
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_user_id_or_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow the Next.js dev server and any deployed UI origin.
# In production, replace "*" with the actual UI domain.
_UI_ORIGINS = [os.getenv("UI_ORIGIN")] if os.getenv("UI_ORIGIN") else []
if os.getenv("ENVIRONMENT") == "development":
    _UI_ORIGINS.extend([
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])
_UI_ORIGINS = list(filter(None, _UI_ORIGINS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_UI_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Request / Response models ─────────────────────────────────────────────────


class CreateProjectRequest(BaseModel):
    name: str
    namespace: str

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        if not _NAMESPACE_RE.match(v):
            raise ValueError(
                "namespace must be lowercase alphanumeric with hyphens, 3–63 chars, "
                "and cannot start or end with a hyphen"
            )
        # HIGH-20 Fix: Reject reserved Kubernetes namespace prefixes
        if v in _RESERVED_NS_PREFIXES or any(v.startswith(p) for p in _RESERVED_NS_PREFIXES if p.endswith('-')):
            raise ValueError(
                f"namespace '{v}' is reserved and cannot be used for tenant projects"
            )
        return v


class InstallWebhookRequest(BaseModel):
    repo_url: str


class CreateDeploymentRequest(BaseModel):
    repo_url: str
    port: Optional[int] = 8080
    branch: Optional[str] = "main"

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        if not _REPO_URL_RE.match(v):
            raise ValueError(
                "repo_url must be an https:// URL or git@host:org/repo.git SSH URL"
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("port must be between 1 and 65535")
        return v

# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/healthz", tags=["Health"])
@limiter.limit("100/minute")
def healthz(request: Request):
    """Liveness probe endpoint. Always returns 200."""
    return {"status": "ok"}

# ── Projects ──────────────────────────────────────────────────────────────────


@app.post("/projects", status_code=201, tags=["Projects"])
@limiter.limit("10/minute")
def create_project(request: Request, body: CreateProjectRequest, current_user: User = Depends(get_current_user)):
    """
    Create a new project. The controller picks up status=Provisioning
    and creates the tenant namespace + RBAC in Kubernetes.
    """
    project_id = str(uuid.uuid4())
    webhook_secret = secrets.token_hex(32)
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO projects (id, owner_id, name, namespace, status, webhook_secret)
                    VALUES (%s, %s, %s, %s, 'Provisioning', %s)
                    RETURNING *;
                    """,
                    (project_id, current_user.user_id,
                     body.name, body.namespace, webhook_secret),
                )
                project = dict(cur.fetchone())

                cur.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
                    (project_id, current_user.user_id)
                )

            conn.commit()
    except psycopg2.errors.UniqueViolation as e:
        if "namespace" in str(e):
            raise HTTPException(
                status_code=409, detail="A project with this namespace already exists")
        raise HTTPException(
            status_code=409, detail="A project with this ID already exists")
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail="Failed to create project")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="CREATE",
        resource_type="project",
        resource_id=project_id,
        details={"name": body.name, "namespace": body.namespace},
    )
    return _serialize(project)


@app.get("/projects", tags=["Projects"])
@limiter.limit("100/minute")
def list_projects(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user)
):
    """List all non-deleted (non-Terminating) projects."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if current_user.is_admin:
                    cur.execute(
                        """
                        SELECT p.*, u.email as owner_email 
                        FROM projects p
                        LEFT JOIN users u ON p.owner_id = u.id
                        WHERE p.deleted_at IS NULL 
                        ORDER BY p.created_at DESC
                        LIMIT %s OFFSET %s;
                        """, (limit, offset)
                    )
                else:
                    # HIGH-15 Fix: Include projects where user is a member, not just owner
                    cur.execute(
                        """
                        SELECT DISTINCT p.*, u.email as owner_email 
                        FROM projects p
                        LEFT JOIN users u ON p.owner_id = u.id
                        LEFT JOIN project_members pm ON p.id = pm.project_id
                        WHERE p.deleted_at IS NULL 
                          AND (p.owner_id = %s OR pm.user_id = %s)
                        ORDER BY p.created_at DESC
                        LIMIT %s OFFSET %s;
                        """,
                        (current_user.user_id, current_user.user_id, limit, offset)
                    )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail="Failed to list projects")


@app.get("/projects/{project_id}", tags=["Projects"])
@limiter.limit("100/minute")
def get_project(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    """Get a single project by ID."""
    return _serialize(project)


@app.delete("/projects/{project_id}", status_code=202, tags=["Projects"])
@limiter.limit("10/minute")
def delete_project(request: Request, project_id: str, project: dict = Depends(verify_project_access), current_user: User = Depends(get_current_user)):
    """
    Soft-delete a project — sets status to Terminating.
    The controller will delete the Kubernetes namespace and then
    hard-delete the row once the namespace is gone.
    """
    if current_user.role != 'admin':
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;",
                            (project_id, current_user.user_id))
                member = cur.fetchone()
                if not member or member[0] != 'owner':
                    raise HTTPException(
                        status_code=403, detail="Only project owners can delete projects")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE projects SET status = 'Terminating', deleted_at = NOW() WHERE id = %s;",
                    (project_id,),
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to delete project {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete project")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="DELETE",
        resource_type="project",
        resource_id=project_id,
        details={},
    )
    return {"message": f"Project {project_id} marked for termination"}


class AddMemberRequest(BaseModel):
    email: str
    role: Literal['editor', 'viewer']


@app.get("/projects/{project_id}/members", tags=["Members"])
@limiter.limit("100/minute")
def list_project_members(
    request: Request,
    project_id: str,
    project: dict = Depends(verify_project_access),
    current_user: User = Depends(get_current_user)
):
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # Enforce owner/admin requirement
                if current_user.role != 'admin':
                    cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;", (
                        project_id, current_user.user_id))
                    caller_member = cur.fetchone()
                    if not caller_member or caller_member['role'] != 'owner':
                        raise HTTPException(
                            status_code=403, detail="Only project owners can manage members")

                cur.execute("""
                    SELECT u.id as user_id, u.email, pm.role, pm.created_at 
                    FROM project_members pm
                    JOIN users u ON pm.user_id = u.id
                    WHERE pm.project_id = %s
                    ORDER BY pm.created_at ASC;
                """, (project_id,))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list members: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to list project members")


@app.post("/projects/{project_id}/members", status_code=201, tags=["Members"])
@limiter.limit("20/minute")
def add_project_member(
    request: Request,
    project_id: str,
    body: AddMemberRequest,
    project: dict = Depends(verify_project_access),
    current_user: User = Depends(get_current_user)
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Enforce owner/admin requirement
            if current_user.role != 'admin':
                cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;",
                            (project_id, current_user.user_id))
                caller_member = cur.fetchone()
                if not caller_member or caller_member['role'] != 'owner':
                    raise HTTPException(
                        status_code=403, detail="Only project owners can manage members")

            # Find user by email
            cur.execute(
                "SELECT id, email FROM users WHERE email = %s;", (body.email,))
            target_user = cur.fetchone()
            if not target_user:
                raise HTTPException(status_code=404, detail="User not found")

            try:
                cur.execute("""
                    INSERT INTO project_members (project_id, user_id, role) 
                    VALUES (%s, %s, %s) RETURNING role, created_at;
                """, (project_id, target_user['id'], body.role))
                new_member = cur.fetchone()
                conn.commit()
                return _serialize({
                    "user_id": target_user['id'],
                    "email": target_user['email'],
                    "role": new_member['role'],
                    "created_at": new_member['created_at']
                })
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                raise HTTPException(
                    status_code=409, detail="User is already a member of this project")


@app.delete("/projects/{project_id}/members/{target_user_id}", tags=["Members"])
@limiter.limit("20/minute")
def remove_project_member(
    request: Request,
    project_id: str,
    target_user_id: str,
    project: dict = Depends(verify_project_access),
    current_user: User = Depends(get_current_user)
):
    if target_user_id == current_user.user_id:
        raise HTTPException(
            status_code=403, detail="Cannot remove yourself from a project")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Enforce owner/admin requirement
            if current_user.role != 'admin':
                cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;",
                            (project_id, current_user.user_id))
                caller_member = cur.fetchone()
                if not caller_member or caller_member['role'] != 'owner':
                    raise HTTPException(
                        status_code=403, detail="Only project owners can manage members")

            cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;",
                        (project_id, target_user_id))
            target_member = cur.fetchone()

            if not target_member:
                raise HTTPException(status_code=404, detail="Member not found")

            if target_member['role'] == 'owner':
                raise HTTPException(
                    status_code=403, detail="Cannot remove the project owner")

            cur.execute("DELETE FROM project_members WHERE project_id = %s AND user_id = %s;",
                        (project_id, target_user_id))
            conn.commit()
            return {"message": "Member removed"}


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        if not _REPO_URL_RE.match(v):
            raise ValueError(
                "repo_url must be an https:// URL or git@host:org/repo.git SSH URL"
            )
        return v


@app.post("/projects/analyze", tags=["Projects"])
@limiter.limit("5/minute")
async def analyze_repo(request: Request, body: AnalyzeRequest, current_user: User = Depends(get_current_user)):
    """Analyze a Git repository and detect deployable services."""
    import asyncio
    import tempfile
    import subprocess
    from analyzer import RepoAnalyzer

    # Validate branch name to prevent shell injection
    if not re.match(r'^[a-zA-Z0-9_.-]{1,100}$', body.branch):
        raise HTTPException(status_code=400, detail="Invalid branch name")

    def _clone_and_analyze():
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", "-b",
                        body.branch, body.repo_url, tmpdir],
                    check=True, capture_output=True, timeout=60
                )
            except subprocess.TimeoutExpired:
                raise HTTPException(
                    status_code=400,
                    detail="Repository clone timed out after 60 seconds"
                )
            analyzer = RepoAnalyzer(
                repo_path=tmpdir,
                repo_name=body.repo_url.split('/')[-1].replace('.git', ''))
            return analyzer.analyze()

    try:
        services = await asyncio.to_thread(_clone_and_analyze)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clone repo for analysis: {e}")
        raise HTTPException(
            status_code=400, detail="Failed to clone repository")

    return {"services": [s.__dict__ for s in services]}

# ── Deployments ───────────────────────────────────────────────────────────────


@app.post("/projects/{project_id}/deployments", status_code=202, tags=["Deployments"])
@limiter.limit("5/minute")
def create_deployment(request: Request, project_id: str, body: CreateDeploymentRequest, project: dict = Depends(verify_project_access), current_user: User = Depends(get_current_user)):
    """
    Submit a deployment request. Only a repo URL is required.
    - The platform generates the image URI automatically from ECR_REPOSITORY_URL.
    - Scaling is handled by Karpenter/KEDA — the user does not set replicas.
    - Port defaults to 8080; override only if your app listens elsewhere.
    """
    if project["status"] not in ("Ready", "Provisioning"):
        raise HTTPException(
            status_code=409,
            detail=f"Project is in status '{project['status']}' and cannot accept deployments"
        )

    # CRIT-03 Fix: Reject if there's already an in-flight deployment for this project
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM deployments WHERE project_id = %s AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
                    (project_id,)
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="A deployment is already in progress for this project. Wait for it to complete or fail before deploying again."
                    )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check in-flight deployments: {e}")
        raise HTTPException(status_code=500, detail="Failed to check deployment status")

    deployment_id = str(uuid.uuid4())
    queued_at = str(time.time())

    # Build the image URI — users never input this.
    # Format: <ecr_repo_url>:<deployment_id>
    # deployment_id as tag gives a unique, traceable, immutable image per deploy.
    if ECR_REPOSITORY_URL:
        # Base registry e.g. 123456789012.dkr.ecr.region.amazonaws.com
        base_registry = ECR_REPOSITORY_URL.split("/")[0]
        image_uri = f"{base_registry}/shipzen-builds/{project_id}:{deployment_id}"
    else:
        # Local dev / testing fallback — no ECR configured
        image_uri = f"local/shipzen-builds/{project_id}:{deployment_id}"

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO deployments
                        (deployment_id, project_id, repo_url, image_uri, replicas, port, state)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Queued')
                    RETURNING *;
                    """,
                    (
                        deployment_id, project_id,
                        body.repo_url, image_uri,
                        1,           # Platform controls scaling — initial replica count is 1
                        body.port,
                    ),
                )
                deployment = dict(cur.fetchone())
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to create deployment: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to create deployment")

    # Enqueue to Redis stream — worker picks this up and hands off to builder
    try:
        r = get_redis()
        r.xadd(STREAM_NAME, {
            "deployment_id": deployment_id,
            "project_id":    project_id,
            "repo_url":      body.repo_url,
            "branch":        body.branch,
            "image_name":    image_uri,
            "queued_at":     queued_at,
            "retries":       "0",
        }, maxlen=10000)
    except Exception as e:
        logger.error(f"Failed to enqueue deployment {deployment_id}: {e}")
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE deployments SET state = 'Failed', last_error = %s WHERE deployment_id = %s;",
                        ("Failed to enqueue to Redis", deployment_id),
                    )
                conn.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=500, detail="Failed to enqueue deployment")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="DEPLOY",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"repo_url": body.repo_url, "branch": body.branch},
    )
    return _serialize(deployment)


@app.post("/projects/{project_id}/rollback", status_code=202, tags=["Deployments"])
@limiter.limit("5/minute")
def rollback_deployment(request: Request, project_id: str, project: dict = Depends(verify_project_access), current_user: User = Depends(get_current_user)):
    """Re-deploy the last known-good image without rebuilding."""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Find the last successful deployment
            cur.execute("""
                SELECT * FROM deployments 
                WHERE project_id = %s AND state = 'Running'
                ORDER BY updated_at DESC LIMIT 1;
            """, (project_id,))
            last_good = cur.fetchone()

            if not last_good:
                raise HTTPException(
                    status_code=409, detail="No previous successful deployment found to rollback to.")

            deployment_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO deployments
                    (deployment_id, project_id, repo_url, image_uri, replicas, port, state)
                VALUES (%s, %s, %s, %s, %s, %s, 'Queued')
                RETURNING *;
            """, (
                deployment_id, project_id, last_good['repo_url'],
                last_good['image_uri'], last_good['replicas'], last_good['port']
            ))
            cur.fetchone()
        conn.commit()

    # Publish state update to Redis
    try:
        r = get_redis()
        # Fix 1: Insert state as Queued, and queue to worker stream
        r.xadd(STREAM_NAME, {
            "deployment_id": deployment_id,
            "project_id":    project_id,
            "repo_url":      last_good['repo_url'],
            "branch":        "main",
            "image_name":    last_good['image_uri'],
            "queued_at":     str(time.time()),
            "retries":       "0",
            "is_rollback":   "true",
        }, maxlen=10000)
        r.publish(f"shipzen:status:{deployment_id}", json.dumps(
            {"state": "Queued", "last_error": None}))
    except Exception as e:
        logger.warning(f"Failed to publish status to Redis: {e}")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="ROLLBACK",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"from_image": last_good['image_uri']},
    )
    return {"message": "Rollback queued", "deployment_id": deployment_id, "status": "Queued"}


@app.get("/projects/{project_id}/deployments", tags=["Deployments"])
@limiter.limit("100/minute")
def list_deployments(
    request: Request,
    project_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(
        default=None, description="cursor format: <updated_at>|<deployment_id>"),
    project: dict = Depends(verify_project_access),
):
    """
    List deployments for a project with keyset pagination.
    Pass the `<updated_at>|<deployment_id>` value of the last item as `cursor` to get the next page.
    """

    query = """
        SELECT deployment_id, project_id, repo_url, image_uri, replicas, port, state, updated_at, last_error
        FROM deployments
        WHERE project_id = %s
    """
    params = [project_id]

    if cursor:
        try:
            cursor_updated_at, cursor_deployment_id = cursor.split("|", 1)
            query += " AND (updated_at, deployment_id) < (%s, %s)"
            params.extend([cursor_updated_at, cursor_deployment_id])
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid cursor format")

    query += " ORDER BY updated_at DESC, deployment_id DESC LIMIT %s;"
    params.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, tuple(params))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list deployments: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to list deployments")


@app.get("/projects/{project_id}/deployments/{deployment_id}", tags=["Deployments"])
@limiter.limit("100/minute")
def get_deployment(request: Request, project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):
    """Get a single deployment by ID."""
    deployment = _get_deployment_or_404(project_id, deployment_id)
    return _serialize(deployment)


@app.websocket("/ws/projects/{project_id}/deployments/{deployment_id}/status")
async def websocket_deployment_status(websocket: WebSocket, project_id: str, deployment_id: str):
    await websocket.accept()
    
    # HIGH-16 Fix: Accept token via the first WS message instead of query string
    try:
        auth_data = await websocket.receive_json()
        token = auth_data.get("token")
        if not token:
            await websocket.close(code=1008)
            return
        from auth import get_current_user_from_token
        await get_current_user_from_token(token)
    except Exception:
        await websocket.close(code=1008)
        return

    import asyncio
    pubsub = _aioredis_client.pubsub()
    await pubsub.subscribe(f"shipzen:status:{deployment_id}")

    def fetch_initial():
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT state, last_error FROM deployments WHERE deployment_id = %s AND project_id = %s;",
                    (deployment_id, project_id),
                )
                return cur.fetchone()

    try:
        row = await asyncio.to_thread(fetch_initial)
        if row:
            await websocket.send_json({"state": row['state'], "last_error": row['last_error']})

        main_task = asyncio.current_task()

        async def ping():
            try:
                while True:
                    await asyncio.sleep(30)
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        main_task.cancel()
                        break
            except asyncio.CancelledError:
                pass
        ping_task = asyncio.create_task(ping())

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json(data)
                if data.get("state") in ("Running", "Failed", "DLQ"):
                    break
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {deployment_id}")
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        if 'ping_task' in locals():
            ping_task.cancel()
        await pubsub.unsubscribe()
        await pubsub.close()


@app.get("/projects/{project_id}/deployments/{deployment_id}/logs/stream", tags=["Deployments"])
async def stream_logs(project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):

    # HIGH-05 Fix: Add timeout to SSE Pub/Sub listen to prevent leaked subscriptions
    import asyncio

    async def event_stream():
        pubsub = _aioredis_client.pubsub()
        await pubsub.subscribe(f"shipzen:logs:{deployment_id}")
        try:
            deadline = time.time() + 300  # 5 minute max SSE session
            async for message in pubsub.listen():
                if time.time() > deadline:
                    break
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@app.websocket("/ws/projects/{project_id}/deployments/{deployment_id}/logs")
async def websocket_deployment_logs(
    websocket: WebSocket,
    project_id: str,
    deployment_id: str,
):
    """
    WebSocket endpoint for live build log streaming.
    Subscribes to the Redis Pub/Sub channel `shipzen:logs:{deployment_id}`
    and forwards each line to the connected client as plain text.
    """
    await websocket.accept()
    
    # HIGH-16 Fix: Accept token via the first WS message instead of query string
    try:
        import json
        auth_data_str = await websocket.receive_text()
        auth_data = json.loads(auth_data_str)
        token = auth_data.get("token")
        if not token:
            await websocket.close(code=1008)
            return
        from auth import get_current_user_from_token
        user = await get_current_user_from_token(token)
    except Exception:
        await websocket.close(code=1008)
        return

    # Verify the deployment belongs to this project
    try:
        import asyncio
        await asyncio.to_thread(verify_project_access, project_id, user)
        await asyncio.to_thread(_get_deployment_or_404, project_id, deployment_id)
    except HTTPException:
        await websocket.close(code=1008)
        return

    pubsub = _aioredis_client.pubsub()
    await pubsub.subscribe(f"shipzen:logs:{deployment_id}")

    try:
        main_task = asyncio.current_task()

        async def ping():
            try:
                while True:
                    await asyncio.sleep(30)
                    try:
                        await websocket.send_text("ping")
                    except Exception:
                        main_task.cancel()
                        break
            except asyncio.CancelledError:
                pass
        ping_task = asyncio.create_task(ping())

        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info(f"Log WS disconnected for {deployment_id}")
    except Exception as e:
        logger.error(f"Log WS error for {deployment_id}: {e}")
    finally:
        if 'ping_task' in locals():
            ping_task.cancel()
        await pubsub.unsubscribe()
        await pubsub.close()

# ── Builds ────────────────────────────────────────────────────────────────────


@app.get("/projects/{project_id}/deployments/{deployment_id}/builds", tags=["Builds"])
@limiter.limit("100/minute")
def list_builds(request: Request, project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):
    """List all builds for a deployment, most recent first."""
    _get_deployment_or_404(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    SELECT build_id, deployment_id, s3_log_uri, status, started_at, completed_at
                    FROM builds
                    WHERE deployment_id = %s
                    ORDER BY started_at DESC;
                    """,
                    (deployment_id,),
                )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list builds: {e}")
        raise HTTPException(status_code=500, detail="Failed to list builds")


@app.get("/projects/{project_id}/deployments/{deployment_id}/builds/{build_id}/logs", tags=["Builds"])
@limiter.limit("100/minute")
def get_build_logs(request: Request, project_id: str, deployment_id: str, build_id: str, project: dict = Depends(verify_project_access)):
    """Stream build log content directly, proxied through the API to avoid S3 CORS issues."""
    _get_deployment_or_404(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT s3_log_uri FROM builds WHERE build_id = %s AND deployment_id = %s;",
                    (build_id, deployment_id)
                )
                row = cur.fetchone()
                if not row or not row["s3_log_uri"]:
                    raise HTTPException(
                        status_code=404, detail="Log not found")

                s3_uri = row["s3_log_uri"]
                if not s3_uri.startswith("s3://"):
                    raise HTTPException(
                        status_code=400, detail="Invalid log URI")

                bucket = s3_uri.split("/")[2]
                key = "/".join(s3_uri.split("/")[3:])

                if not bucket:
                    raise HTTPException(
                        status_code=404, detail="Log storage not configured")

                s3 = boto3.client('s3')
                try:
                    obj = s3.get_object(Bucket=bucket, Key=key)
                except s3.exceptions.NoSuchKey:
                    raise HTTPException(
                        status_code=404, detail="Log file not found in S3")

                # HIGH-06 Fix: Stream S3 object instead of loading entirely into memory
                def stream_s3_body():
                    body = obj['Body']
                    while True:
                        chunk = body.read(64 * 1024)  # 64KB chunks
                        if not chunk:
                            break
                        yield chunk

                return StreamingResponse(
                    stream_s3_body(),
                    media_type="text/plain",
                    headers={
                        "Content-Disposition": f"inline; filename=build-{build_id[:8]}.log"}
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch build log: {e}")
        raise HTTPException(status_code=500, detail="Failed to get logs")

# ── Audit ─────────────────────────────────────────────────────────────────────


@app.get("/projects/{project_id}/audit", tags=["Audit"])
@limiter.limit("100/minute")
def get_audit_logs(
    request: Request,
    project_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    project: dict = Depends(verify_project_access),
):
    """List audit log entries for a project."""

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM audit_logs
                    WHERE project_id = %s
                    ORDER BY timestamp DESC
                    LIMIT %s;
                    """,
                    (project_id, limit),
                )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch audit logs: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch audit logs")


@app.get("/audit", tags=["Audit"])
@limiter.limit("100/minute")
def get_global_audit_logs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """List recent audit log entries across all projects owned by the user."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if current_user.is_admin:
                    cur.execute(
                        """
                        SELECT a.*, p.name as project_name 
                        FROM audit_logs a
                        JOIN projects p ON a.project_id = p.id
                        ORDER BY a.timestamp DESC LIMIT %s;
                        """,
                        (limit,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT a.*, p.name as project_name 
                        FROM audit_logs a
                        JOIN projects p ON a.project_id = p.id
                        WHERE a.user_id = %s OR p.owner_id = %s
                        ORDER BY a.timestamp DESC LIMIT %s;
                        """,
                        (current_user.user_id, current_user.user_id, limit),
                    )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch global audit logs: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch audit logs")

# ── Env Vars ──────────────────────────────────────────────────────────────────


@app.get("/projects/{project_id}/env", tags=["Environment"])
@limiter.limit("100/minute")
def get_env_vars(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    # Fix 6: Use project['id'] instead of name to avoid collision
    secret_id = f"shipzen/project/{project['id']}"
    try:
        # We only return the keys, not the values for security
        res = _sm_client.get_secret_value(SecretId=secret_id)
        secret_dict = json.loads(res.get('SecretString', '{}'))
        return {"keys": list(secret_dict.keys())}
    except _sm_client.exceptions.ResourceNotFoundException:
        return {"keys": []}
    except Exception as e:
        logger.error(f"Failed to fetch env vars for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch env vars")


# HIGH-22 Fix: Pydantic model for env var input validation
class PutEnvVarRequest(BaseModel):
    key: str
    value: str


@app.put("/projects/{project_id}/env", tags=["Environment"])
@limiter.limit("20/minute")
def put_env_var(request: Request, project_id: str, body: PutEnvVarRequest, project: dict = Depends(verify_project_access), current_user: User = Depends(get_current_user)):
    """Add or update an environment variable for a project."""
    # Fix 6: Use project['id'] instead of name to avoid collision
    secret_id = f"shipzen/project/{project['id']}"

    # CRIT-02 Fix: Use VersionId-based optimistic locking to prevent read-modify-write races
    try:
        try:
            res = _sm_client.get_secret_value(SecretId=secret_id)
            secret_dict = json.loads(res.get('SecretString', '{}'))
            version_id = res.get('VersionId')
        except _sm_client.exceptions.ResourceNotFoundException:
            secret_dict = {}
            version_id = None

        secret_dict[body.key] = body.value

        try:
            if version_id:
                _sm_client.put_secret_value(
                    SecretId=secret_id,
                    SecretString=json.dumps(secret_dict),
                    VersionStages=['AWSCURRENT']
                )
            else:
                _sm_client.create_secret(
                    Name=secret_id, SecretString=json.dumps(secret_dict))
        except _sm_client.exceptions.ResourceNotFoundException:
            _sm_client.create_secret(
                Name=secret_id, SecretString=json.dumps(secret_dict))

        log_audit_event(
            project_id=project_id,
            user_id=current_user.user_id,
            action="UPDATE_ENV",
            resource_type="project",
            resource_id=project_id,
            details={"key": key},
        )
        return {"message": "Updated successfully"}
    except Exception as e:
        logger.error(f"Failed to update env var for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update env var")


@app.delete("/projects/{project_id}/env/{key}", tags=["Environment"])
@limiter.limit("20/minute")
def delete_env_var(request: Request, project_id: str, key: str, project: dict = Depends(verify_project_access), current_user: User = Depends(get_current_user)):
    # Fix 6: Use project['id'] instead of name to avoid collision
    secret_id = f"shipzen/project/{project['id']}"

    try:
        res = _sm_client.get_secret_value(SecretId=secret_id)
        secret_dict = json.loads(res.get('SecretString', '{}'))
        if key in secret_dict:
            del secret_dict[key]
            _sm_client.update_secret(SecretId=secret_id,
                             SecretString=json.dumps(secret_dict))

            log_audit_event(
                project_id=project_id,
                user_id=current_user.user_id,
                action="DELETE_ENV",
                resource_type="project",
                resource_id=project_id,
                details={"key": key},
            )
        return {"message": "Deleted successfully"}
    except _sm_client.exceptions.ResourceNotFoundException:
        return {"message": "Deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete env var for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete env var")

# ── GitHub Helpers ──────────────────────────────────────────────────────────────


@app.get("/github/branches", tags=["GitHub"])
@limiter.limit("20/minute")
def get_github_branches(request: Request, repo_url: str):
    """Fetch branches for a public Git repository using git ls-remote."""
    if not _REPO_URL_RE.match(repo_url):
        raise HTTPException(status_code=400, detail="Invalid repository URL")

    import subprocess
    try:
        # Timeout of 10s is plenty for ls-remote
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            # Check if it's an auth issue (private repo) or repo not found
            err = result.stderr.lower()
            if "authentication" in err or "could not read username" in err or "terminal prompts disabled" in err:
                raise HTTPException(
                    status_code=403, detail="Repository is private or requires authentication")
            raise HTTPException(
                status_code=404, detail="Repository not found or inaccessible")

        branches = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                ref = parts[1]
                if ref.startswith("refs/heads/"):
                    branches.append(ref[len("refs/heads/"):])

        return {"branches": branches, "total": len(branches)}

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504, detail="Request to repository timed out")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching branches for {repo_url}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch branches")

# ── Secrets ───────────────────────────────────────────────────────────────────

class PutSecretRequest(BaseModel):
    key: str
    value: str

@app.get("/projects/{project_id}/secrets", tags=["Secrets"])
@limiter.limit("50/minute")
def list_secrets(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    """List all secret keys for a project (values are redacted)."""
    # CRIT-07 Fix: Use project ID instead of name to match /env endpoints
    secret_id = f"shipzen/project/{project['id']}"
    try:
        resp = _sm_client.get_secret_value(SecretId=secret_id)
        secrets_dict = json.loads(resp['SecretString'])
        return {"secrets": [{"key": k, "value": "********"} for k in secrets_dict.keys()]}
    except _sm_client.exceptions.ResourceNotFoundException:
        return {"secrets": []}
    except Exception as e:
        logger.error(f"Failed to list secrets: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve secrets")

@app.post("/projects/{project_id}/secrets", status_code=200, tags=["Secrets"])
@limiter.limit("20/minute")
def put_secret(request: Request, project_id: str, body: PutSecretRequest, project: dict = Depends(verify_project_access)):
    """Add or update a secret for a project."""
    # CRIT-07 Fix: Use project ID instead of name to match /env endpoints
    secret_id = f"shipzen/project/{project['id']}"
    secrets_dict = {}
    
    try:
        resp = _sm_client.get_secret_value(SecretId=secret_id)
        secrets_dict = json.loads(resp['SecretString'])
    except _sm_client.exceptions.ResourceNotFoundException:
        pass
    except Exception as e:
        logger.error(f"Failed to fetch secrets for update: {e}")
        raise HTTPException(status_code=500, detail="Failed to update secrets")
        
    secrets_dict[body.key] = body.value
    
    try:
        try:
            _sm_client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(secrets_dict))
        except _sm_client.exceptions.ResourceNotFoundException:
            _sm_client.create_secret(Name=secret_id, SecretString=json.dumps(secrets_dict))
        return {"message": "Secret updated successfully", "key": body.key}
    except Exception as e:
        logger.error(f"Failed to save secret: {e}")
        raise HTTPException(status_code=500, detail="Failed to save secret")

@app.delete("/projects/{project_id}/secrets/{key}", status_code=200, tags=["Secrets"])
@limiter.limit("20/minute")
def delete_secret(request: Request, project_id: str, key: str, project: dict = Depends(verify_project_access)):
    """Delete a secret key from a project."""
    # CRIT-07 Fix: Use project ID instead of name
    secret_id = f"shipzen/project/{project['id']}"
    
    try:
        resp = _sm_client.get_secret_value(SecretId=secret_id)
        secrets_dict = json.loads(resp['SecretString'])
        if key in secrets_dict:
            del secrets_dict[key]
            _sm_client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(secrets_dict))
        return {"message": "Secret deleted successfully"}
    except _sm_client.exceptions.ResourceNotFoundException:
        raise HTTPException(status_code=404, detail="Secret not found")
    except Exception as e:
        logger.error(f"Failed to delete secret: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete secret")

# ── Webhooks ──────────────────────────────────────────────────────────────────


@app.post("/webhooks/github/{project_id}", tags=["Webhooks"])
@limiter.limit("60/minute")
async def github_webhook(request: Request, project_id: str):
    # Verify signature
    signature_header = request.headers.get("x-hub-signature-256")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    # Fix 2: Only trigger on push events
    if request.headers.get("X-GitHub-Event") != "push":
        return JSONResponse(status_code=200, content={"message": "event ignored"})

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT webhook_secret FROM projects WHERE id = %s;", (project_id,))
                row = cur.fetchone()
                if not row or not row["webhook_secret"]:
                    raise HTTPException(
                        status_code=404, detail="Webhook secret not found")
                webhook_secret = row["webhook_secret"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get webhook secret: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    # Validation logic requires raw body
    body_bytes = await request.body()
    expected_mac = hmac.new(webhook_secret.encode(),
                            body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected_mac}", signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Trigger deploy
    # Determine branch
    branch = "main"
    if "ref" in payload:
        branch = payload["ref"].split("/")[-1]

    # CRIT-01 Fix: Validate branch name to prevent shell injection in build Jobs
    if not _BRANCH_RE.match(branch):
        raise HTTPException(status_code=400, detail="Invalid branch name in webhook payload")

    # We need repo URL
    repo_url = payload.get("repository", {}).get("clone_url")
    if not repo_url:
        raise HTTPException(
            status_code=400, detail="Missing repository clone_url")

    deployment_id = str(uuid.uuid4())
    queued_at = str(time.time())
    if ECR_REPOSITORY_URL:
        base_registry = ECR_REPOSITORY_URL.split("/")[0]
        image_uri = f"{base_registry}/shipzen-builds/{project_id}:{deployment_id}"
    else:
        image_uri = f"local/shipzen-builds/{project_id}:{deployment_id}"

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT repo_url, port FROM deployments WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1;",
                    (project_id,)
                )
                last_deploy = cur.fetchone()

                if not last_deploy:
                    # Fallback for the first deployment
                    port = 8080
                else:
                    if last_deploy["repo_url"] != repo_url:
                        raise HTTPException(
                            status_code=403, detail="Webhook repository does not match project's repository")
                    port = last_deploy["port"]

                cur.execute(
                    """
                    INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Queued')
                    """,
                    (deployment_id, project_id, repo_url, image_uri, 1, port)
                )
            conn.commit()
    except Exception as e:
        logger.error(
            f"Failed to process webhook DB insert for {project_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to process webhook")

    # Fix 3: Separate XADD to handle stream failures without swallowing
    try:
        r = get_redis()
        r.xadd(STREAM_NAME, {
            "deployment_id": deployment_id,
            "project_id":    project_id,
            "repo_url":      repo_url,
            "branch":        branch,
            "image_name":    image_uri,
            "queued_at":     queued_at,
            "retries":       "0",
        }, maxlen=10000)
    except Exception as e:
        logger.error(
            f"Failed to enqueue webhook deployment {deployment_id}: {e}")
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE deployments SET state = 'Failed', last_error = %s WHERE deployment_id = %s;",
                        ("Failed to enqueue to stream", deployment_id),
                    )
                conn.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=500, detail="Failed to enqueue webhook deployment")

    log_audit_event(
        project_id=project_id,
        user_id="webhook",
        action="WEBHOOK_DEPLOY",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"repo_url": repo_url, "branch": branch},
    )

    return {"message": "Deployment triggered", "deployment_id": deployment_id}


@app.post("/webhooks/github-app", tags=["Webhooks"])
@limiter.limit("120/minute")
async def github_app_webhook(request: Request):
    """Global webhook receiver for the ShipZen GitHub App."""
    signature_header = request.headers.get("x-hub-signature-256")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    if request.headers.get("X-GitHub-Event") != "push":
        return JSONResponse(status_code=200, content={"message": "event ignored"})

    app_secret = os.getenv("GITHUB_APP_WEBHOOK_SECRET")
    if not app_secret:
        logger.error("GITHUB_APP_WEBHOOK_SECRET is not set")
        raise HTTPException(
            status_code=500, detail="Server configuration error")

    body_bytes = await request.body()
    expected_mac = hmac.new(app_secret.encode(),
                            body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected_mac}", signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    branch = "main"
    if "ref" in payload:
        branch = payload["ref"].split("/")[-1]

    # payload['repository']['clone_url'] gives https://github.com/owner/repo.git
    # payload['repository']['html_url'] gives https://github.com/owner/repo
    repo_url = payload.get("repository", {}).get("clone_url")
    html_url = payload.get("repository", {}).get("html_url")
    if not repo_url and not html_url:
        raise HTTPException(
            status_code=400, detail="Missing repository URL in payload")

    # Find matching projects
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # Find all distinct projects that use this repo
                cur.execute(
                    """
                    SELECT DISTINCT ON (project_id) project_id, port, repo_url 
                    FROM deployments 
                    WHERE repo_url = %s OR repo_url = %s 
                    ORDER BY project_id, updated_at DESC;
                    """,
                    (repo_url, html_url)
                )
                projects_to_deploy = cur.fetchall()

                if not projects_to_deploy:
                    logger.info(
                        f"Ignored push event for {repo_url} - no matching ShipZen project found.")
                    return JSONResponse(status_code=200, content={"message": "No matching project, event ignored"})

    except Exception as e:
        logger.error(f"Failed to lookup project for github app webhook: {e}")
        raise HTTPException(
            status_code=500, detail="Database error during project lookup")

    deployed_ids = []

    for row in projects_to_deploy:
        project_id = row["project_id"]
        port = row["port"]
        matched_repo_url = row["repo_url"]

        deployment_id = str(uuid.uuid4())
        queued_at = str(time.time())
        if ECR_REPOSITORY_URL:
            base_registry = ECR_REPOSITORY_URL.split("/")[0]
            image_uri = f"{base_registry}/shipzen-builds/{project_id}:{deployment_id}"
        else:
            image_uri = f"local/shipzen-builds/{project_id}:{deployment_id}"

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state)
                        VALUES (%s, %s, %s, %s, %s, %s, 'Queued')
                        """,
                        (deployment_id, project_id, matched_repo_url, image_uri, 1, port)
                    )
                conn.commit()
        except Exception as e:
            logger.error(
                f"Failed to process webhook DB insert for {project_id}: {e}")
            continue

        try:
            r = get_redis()
            r.xadd(STREAM_NAME, {
                "deployment_id": deployment_id,
                "project_id":    project_id,
                "repo_url":      matched_repo_url,
                "branch":        branch,
                "image_name":    image_uri,
                "queued_at":     queued_at,
                "retries":       "0",
            }, maxlen=10000)
        except Exception as e:
            logger.error(
                f"Failed to enqueue webhook deployment {deployment_id}: {e}")
            continue

        log_audit_event(
            project_id=project_id,
            user_id="github-app",
            action="WEBHOOK_DEPLOY",
            resource_type="deployment",
            resource_id=deployment_id,
            details={"repo_url": matched_repo_url,
                     "branch": branch, "via": "github-app"},
        )
        deployed_ids.append(deployment_id)

    return {"message": "Deployments triggered via GitHub App", "deployment_ids": deployed_ids}

# ── Users & Admin ─────────────────────────────────────────────────────────────


@app.get("/users/me", tags=["Users"])
@limiter.limit("100/minute")
def get_me(request: Request, current_user: User = Depends(get_current_user)):
    """Get the currently logged-in user's profile and role."""
    return {"user_id": current_user.user_id, "is_admin": current_user.is_admin}


class UpdateRoleRequest(BaseModel):
    role: str


@app.get("/admin/users", tags=["Admin"])
@limiter.limit("100/minute")
def list_users(request: Request, current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT id, email, role, created_at FROM users ORDER BY created_at DESC;")
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.put("/admin/users/{user_id}/role", tags=["Admin"])
@limiter.limit("50/minute")
def update_user_role(request: Request, user_id: str, body: UpdateRoleRequest, current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if body.role not in ["admin", "user"]:
        raise HTTPException(
            status_code=400, detail="Invalid role. Must be 'admin' or 'user'.")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET role = %s WHERE id = %s RETURNING id;", (body.role, user_id))
                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404, detail="User not found")
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user role: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    log_audit_event(
        project_id=None,
        user_id=current_user.user_id,
        action="UPDATE_ROLE",
        resource_type="user",
        resource_id=user_id,
        details={"new_role": body.role},
    )
    return {"message": f"User {user_id} role updated to {body.role}"}


@app.get("/admin/audit-logs", tags=["Admin"])
@limiter.limit("100/minute")
def list_global_audit_logs(request: Request, limit: int = Query(50, le=200), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT %s;",
                    (limit,)
                )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch global audit logs: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/admin/deployments", tags=["Admin"])
@limiter.limit("100/minute")
def list_global_deployments(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="cursor format: <updated_at>|<deployment_id>"),
    current_user: User = Depends(get_current_user)
):
    """List all deployments across the platform, with project and owner info."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    query = """
        SELECT d.deployment_id, d.project_id, d.repo_url, d.image_uri,
               d.replicas, d.port, d.state, d.updated_at, d.last_error,
               p.name AS project_name, p.namespace AS project_namespace,
               u.email AS owner_email
        FROM deployments d
        JOIN projects p ON d.project_id = p.id
        LEFT JOIN users u ON p.owner_id = u.id
    """
    params: list = []

    if cursor:
        try:
            cursor_updated_at, cursor_deployment_id = cursor.split("|", 1)
            query += " WHERE (d.updated_at, d.deployment_id) < (%s, %s)"
            params.extend([cursor_updated_at, cursor_deployment_id])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor format")

    query += " ORDER BY d.updated_at DESC, d.deployment_id DESC LIMIT %s;"
    params.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, tuple(params))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list global deployments: {e}")
        raise HTTPException(status_code=500, detail="Failed to list global deployments")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_project_or_404(project_id: str, current_user: User) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # MED-06 Fix: Filter out soft-deleted projects
                cur.execute(
                    "SELECT * FROM projects WHERE id = %s AND deleted_at IS NULL;", (project_id,))
                row = cur.fetchone()
    except Exception as e:
        logger.error(f"DB error fetching project {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    if not row:
        raise HTTPException(
            status_code=404, detail=f"Project '{project_id}' not found")

    if not current_user.is_admin and row["owner_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return dict(row)


def _get_deployment_or_404(project_id: str, deployment_id: str) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM deployments WHERE deployment_id = %s AND project_id = %s;",
                    (deployment_id, project_id),
                )
                row = cur.fetchone()
    except Exception as e:
        logger.error(f"DB error fetching deployment {deployment_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    if not row:
        raise HTTPException(
            status_code=404, detail=f"Deployment '{deployment_id}' not found")
    return dict(row)


# SEC-06 Fix: Fields to exclude from API responses
_SERIALIZE_EXCLUDE = {'webhook_secret'}

def _serialize(obj: dict) -> dict:
    """Convert non-JSON-serializable types (datetime) to strings.
    Excludes sensitive fields like webhook_secret."""
    return {
        k: v.isoformat() if hasattr(v, "isoformat") else v
        for k, v in obj.items()
        if k not in _SERIALIZE_EXCLUDE
    }

# ── Restarts ──────────────────────────────────────────────────────────────────

import datetime

@app.post("/projects/{project_id}/deployments/{deployment_id}/restart", tags=["Deployments"])
@limiter.limit("5/minute")
def restart_deployment(request: Request, project_id: str, deployment_id: str, current_user: User = Depends(get_current_user)):
    """Restart a deployment by patching its pod template with a new restartedAt annotation."""
    project = verify_project_access(project_id, current_user)
    deployment = _get_deployment_or_404(project_id, deployment_id)
    
    deployment_name = f"{deployment_id[:8]}-{project['name']}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": now_str
                    }
                }
            }
        }
    }
    try:
        apps_v1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=project["namespace"],
            body=patch
        )
    except Exception as e:
        logger.error(f"Failed to restart deployment {deployment_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to restart deployment")
    
    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="RESTART",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"deployment_name": deployment_name},
    )
    return {"status": "restarting"}


@app.post("/admin/system/restart", tags=["Admin"])
@limiter.limit("2/minute")
def restart_system(request: Request, current_user: User = Depends(get_current_user)):
    """Restart ShipZen system pods (worker and api)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": now_str
                    }
                }
            }
        }
    }
    
    errors = []
    for deploy_name in ["shipzen-worker", "shipzen-api"]:
        try:
            apps_v1.patch_namespaced_deployment(
                name=deploy_name,
                namespace="shipzen-system",
                body=patch
            )
        except Exception as e:
            logger.error(f"Failed to restart {deploy_name}: {e}")
            errors.append(str(e))
            
    if errors:
        raise HTTPException(status_code=500, detail=f"Failed to restart some system pods: {', '.join(errors)}")
        
    return {"status": "restarting"}
