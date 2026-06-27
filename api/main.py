"""
ShipZen API Server — Phase 16
FastAPI service that is the sole HTTP entry point for the platform.
All state-changing operations write to PostgreSQL and enqueue to Redis.
The controller and worker drive everything asynchronously from there.
"""

import os
import re
import time
import uuid
import logging
from typing import Optional

import redis as redis_lib
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('api')

# ── Config ────────────────────────────────────────────────────────────────────

REDIS_HOST  = os.getenv("REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
REDIS_PORT  = int(os.getenv("REDIS_PORT", "6379"))
STREAM_NAME = os.getenv("STREAM_NAME", "deploy_stream")

# ECR repository URL — injected by Terraform at deploy time.
# The API constructs the full image URI as: <ECR_URL>:<deployment_id>
# Users never see or input this value.
ECR_REPOSITORY_URL = os.getenv("ECR_REPOSITORY_URL", "")

# Repo URL allowlist — same pattern used in builder/main.py
_REPO_URL_RE = re.compile(
    r'^(https://[a-zA-Z0-9._/:\-@]+\.git'
    r'|https://[a-zA-Z0-9._/:\-@]+'
    r'|git@[a-zA-Z0-9._\-]+:[a-zA-Z0-9._/\-]+\.git)$'
)

# Kubernetes namespace name rules: lowercase alphanumeric and hyphens, 3–63 chars
_NAMESPACE_RE = re.compile(r'^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$')

# ── Redis client ──────────────────────────────────────────────────────────────

def get_redis() -> redis_lib.Redis:
    return redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

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
            import jwt
            # For rate limiting, it's cheaper to just decode without full validation
            payload = jwt.decode(token, options={"verify_signature": False})
            if "sub" in payload:
                # Fix 5: Hash token instead of unverified JWT decode for rate limit key
                return hashlib.sha256(token.encode()).hexdigest()[:32]
        except Exception:
            pass
    return get_remote_address(request)

limiter = Limiter(key_func=_user_id_or_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow the Next.js dev server and any deployed UI origin.
# In production, replace "*" with the actual UI domain.
_UI_ORIGINS = list(filter(None, [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    os.getenv("UI_ORIGIN"),
]))

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
                    (project_id, current_user.user_id, body.name, body.namespace, webhook_secret),
                )
                project = dict(cur.fetchone())
                
                cur.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
                    (project_id, current_user.user_id)
                )
                
            conn.commit()
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="A project with this ID already exists")
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
def list_projects(request: Request, current_user: User = Depends(get_current_user)):
    """List all non-deleted (non-Terminating) projects."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if current_user.is_admin:
                    cur.execute(
                        "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY created_at DESC;"
                    )
                else:
                    cur.execute(
                        "SELECT * FROM projects WHERE deleted_at IS NULL AND owner_id = %s ORDER BY created_at DESC;",
                        (current_user.user_id,)
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
                cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;", (project_id, current_user.user_id))
                member = cur.fetchone()
                if not member or member[0] != 'owner':
                    raise HTTPException(status_code=403, detail="Only project owners can delete projects")

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

from typing import Literal

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
                    cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;", (project_id, current_user.user_id))
                    caller_member = cur.fetchone()
                    if not caller_member or caller_member['role'] != 'owner':
                        raise HTTPException(status_code=403, detail="Only project owners can manage members")

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
        raise HTTPException(status_code=500, detail="Failed to list project members")

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
                cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;", (project_id, current_user.user_id))
                caller_member = cur.fetchone()
                if not caller_member or caller_member['role'] != 'owner':
                    raise HTTPException(status_code=403, detail="Only project owners can manage members")

            # Find user by email
            cur.execute("SELECT id, email FROM users WHERE email = %s;", (body.email,))
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
                raise HTTPException(status_code=409, detail="User is already a member of this project")

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
        raise HTTPException(status_code=403, detail="Cannot remove yourself from a project")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Enforce owner/admin requirement
            if current_user.role != 'admin':
                cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;", (project_id, current_user.user_id))
                caller_member = cur.fetchone()
                if not caller_member or caller_member['role'] != 'owner':
                    raise HTTPException(status_code=403, detail="Only project owners can manage members")

            cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;", (project_id, target_user_id))
            target_member = cur.fetchone()
            
            if not target_member:
                raise HTTPException(status_code=404, detail="Member not found")
                
            if target_member['role'] == 'owner':
                raise HTTPException(status_code=403, detail="Cannot remove the project owner")

            cur.execute("DELETE FROM project_members WHERE project_id = %s AND user_id = %s;", (project_id, target_user_id))
            conn.commit()
            return {"message": "Member removed"}

class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"

@app.post("/projects/analyze", tags=["Projects"])
@limiter.limit("5/minute")
def analyze_repo(request: Request, body: AnalyzeRequest, current_user: User = Depends(get_current_user)):
    """Analyze a Git repository and detect deployable services."""
    import tempfile
    import subprocess
    from analyzer import RepoAnalyzer
    
    # Fix 4: Validate branch name to prevent shell injection
    if not re.match(r'^[a-zA-Z0-9_.-]{1,100}$', body.branch):
        raise HTTPException(status_code=400, detail="Invalid branch name")
        
    try:
        # Fix 4: Move TemporaryDirectory inside try
        with tempfile.TemporaryDirectory() as tmpdir:
            # Fix 4: timeout=60, capture_output=True
            subprocess.run(
                ["git", "clone", "--depth", "1", "-b", body.branch, body.repo_url, tmpdir],
                check=True, capture_output=True, timeout=60
            )
            analyzer = RepoAnalyzer(repo_path=tmpdir, repo_name=body.repo_url.split('/')[-1].replace('.git', ''))
            services = analyzer.analyze()
    except Exception as e:
        logger.error(f"Failed to clone repo for analysis: {e}")
        raise HTTPException(status_code=400, detail="Failed to clone repository")
        
    return {"services": [s.__dict__ for s in services]}

@app.get("/github/branches", tags=["GitHub"])
@limiter.limit("30/minute")
def get_github_branches(
    request: Request,
    repo_url: str,
    current_user: User = Depends(get_current_user)
):
    import httpx
    import re
    
    match = re.match(r'^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$', repo_url)
    if not match:
        return JSONResponse(status_code=400, content={"error": "Only GitHub repositories are supported"})
        
    owner, repo = match.groups()
    
    headers = {"Accept": "application/vnd.github+json"}
    auth_header = request.headers.get("Authorization")
    if auth_header:
        headers["Authorization"] = auth_header
        
    branches = []
    
    with httpx.Client(timeout=5) as client:
        for page in range(1, 4):
            url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100&page={page}"
            
            resp = client.get(url, headers=headers)
            
            # Fallback to unauthenticated on 401/403 for public repos
            if resp.status_code in (401, 403) and "Authorization" in headers:
                del headers["Authorization"]
                resp = client.get(url, headers=headers)
                
            if resp.status_code == 404:
                return JSONResponse(
                    status_code=404, 
                    content={"error": "Repository not found or private — check the URL and your GitHub permissions"}
                )
            elif resp.status_code != 200:
                return JSONResponse(status_code=502, content={"error": "Failed to fetch branches from GitHub"})
                
            page_data = resp.json()
            if not page_data:
                break
                
            branches.extend([b["name"] for b in page_data])
            
            if len(page_data) < 100:
                break

    return {"branches": branches, "total": len(branches)}

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
        raise HTTPException(status_code=500, detail="Failed to create deployment")

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
        })
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
        raise HTTPException(status_code=500, detail="Failed to enqueue deployment")

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
                raise HTTPException(status_code=409, detail="No previous successful deployment found to rollback to.")
                
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
            new_dep = dict(cur.fetchone())
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
        })
        r.publish(f"shipzen:status:{deployment_id}", json.dumps({"state": "Queued", "last_error": None}))
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
    cursor: Optional[str] = Query(default=None, description="cursor format: <updated_at>|<deployment_id>"),
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
            raise HTTPException(status_code=400, detail="Invalid cursor format")

    query += " ORDER BY updated_at DESC, deployment_id DESC LIMIT %s;"
    params.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, tuple(params))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list deployments: {e}")
        raise HTTPException(status_code=500, detail="Failed to list deployments")


@app.get("/projects/{project_id}/deployments/{deployment_id}", tags=["Deployments"])
@limiter.limit("100/minute")
def get_deployment(request: Request, project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):
    """Get a single deployment by ID."""
    deployment = _get_deployment_or_404(project_id, deployment_id)
    return _serialize(deployment)

@app.websocket("/ws/projects/{project_id}/deployments/{deployment_id}/status")
async def websocket_deployment_status(websocket: WebSocket, project_id: str, deployment_id: str, token: str = Query(None)):
    if not token:
        await websocket.close(code=1008)
        return
    from auth import get_current_user_from_token
    try:
        user = get_current_user_from_token(token)
    except Exception:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    import redis.asyncio as aioredis
    import asyncio
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    pubsub = r.pubsub()
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
        await pubsub.unsubscribe()
        await r.aclose()


@app.get("/projects/{project_id}/deployments/{deployment_id}/logs/stream", tags=["Deployments"])
async def stream_logs(project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):
    
    import redis.asyncio as aioredis
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    
    async def event_stream():
        pubsub = r.pubsub()
        await pubsub.subscribe(f"shipzen:logs:{deployment_id}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe()
            await r.aclose()

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
    token: str = Query(None),
):
    """
    WebSocket endpoint for live build log streaming.
    Subscribes to the Redis Pub/Sub channel `shipzen:logs:{deployment_id}`
    and forwards each line to the connected client as plain text.
    Auth is passed via ?token= query param (same pattern as the status WS).
    """
    if not token:
        await websocket.close(code=1008)
        return
    from auth import get_current_user_from_token
    try:
        user = get_current_user_from_token(token)
    except Exception:
        await websocket.close(code=1008)
        return

    # Verify the deployment belongs to this project
    try:
        await verify_project_access(project_id, user)
        import asyncio
        await asyncio.to_thread(_get_deployment_or_404, project_id, deployment_id)
    except HTTPException:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    import redis.asyncio as aioredis
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"shipzen:logs:{deployment_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info(f"Log WS disconnected for {deployment_id}")
    except Exception as e:
        logger.error(f"Log WS error for {deployment_id}: {e}")
    finally:
        await pubsub.unsubscribe()
        await r.aclose()

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
                    raise HTTPException(status_code=404, detail="Log not found")

                s3_uri = row["s3_log_uri"]
                if not s3_uri.startswith("s3://"):
                    raise HTTPException(status_code=400, detail="Invalid log URI")

                bucket = s3_uri.split("/")[2]
                key = "/".join(s3_uri.split("/")[3:])

                if not bucket:
                    raise HTTPException(status_code=404, detail="Log storage not configured")

                s3 = boto3.client('s3')
                try:
                    obj = s3.get_object(Bucket=bucket, Key=key)
                except s3.exceptions.NoSuchKey:
                    raise HTTPException(status_code=404, detail="Log file not found in S3")

                content = obj['Body'].read()
                return Response(
                    content=content,
                    media_type="text/plain",
                    headers={"Content-Disposition": f"inline; filename=build-{build_id[:8]}.log"}
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
        raise HTTPException(status_code=500, detail="Failed to fetch audit logs")

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
        raise HTTPException(status_code=500, detail="Failed to fetch audit logs")

# ── Env Vars ──────────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/env", tags=["Environment"])
@limiter.limit("100/minute")
def get_env_vars(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    # Fix 6: Use project['id'] instead of name to avoid collision
    secret_id = f"shipzen/project/{project['id']}"
    sm = boto3.client('secretsmanager')
    try:
        # We only return the keys, not the values for security
        res = sm.get_secret_value(SecretId=secret_id)
        import json
        secret_dict = json.loads(res.get('SecretString', '{}'))
        return {"keys": list(secret_dict.keys())}
    except sm.exceptions.ResourceNotFoundException:
        return {"keys": []}
    except Exception as e:
        logger.error(f"Failed to fetch env vars for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch env vars")

@app.put("/projects/{project_id}/env", tags=["Environment"])
@limiter.limit("20/minute")
def put_env_var(request: Request, project_id: str, body: dict, project: dict = Depends(verify_project_access)):
    """Expected body: {"key": "API_KEY", "value": "secret123"}"""
    key = body.get("key")
    value = body.get("value")
    if not key or not value:
        raise HTTPException(status_code=400, detail="Missing key or value")
        
    # Fix 6: Use project['id'] instead of name to avoid collision
    secret_id = f"shipzen/project/{project['id']}"
    sm = boto3.client('secretsmanager')
    import json
    
    try:
        try:
            res = sm.get_secret_value(SecretId=secret_id)
            secret_dict = json.loads(res.get('SecretString', '{}'))
        except sm.exceptions.ResourceNotFoundException:
            secret_dict = {}
            
        secret_dict[key] = value
        
        try:
            sm.update_secret(SecretId=secret_id, SecretString=json.dumps(secret_dict))
        except sm.exceptions.ResourceNotFoundException:
            sm.create_secret(Name=secret_id, SecretString=json.dumps(secret_dict))
            
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
    sm = boto3.client('secretsmanager')
    import json
    
    try:
        res = sm.get_secret_value(SecretId=secret_id)
        secret_dict = json.loads(res.get('SecretString', '{}'))
        if key in secret_dict:
            del secret_dict[key]
            sm.update_secret(SecretId=secret_id, SecretString=json.dumps(secret_dict))
            
            log_audit_event(
                project_id=project_id,
                user_id=current_user.user_id,
                action="DELETE_ENV",
                resource_type="project",
                resource_id=project_id,
                details={"key": key},
            )
        return {"message": "Deleted successfully"}
    except sm.exceptions.ResourceNotFoundException:
        return {"message": "Deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete env var for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete env var")

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
                cur.execute("SELECT webhook_secret FROM projects WHERE id = %s;", (project_id,))
                row = cur.fetchone()
                if not row or not row["webhook_secret"]:
                    raise HTTPException(status_code=404, detail="Webhook secret not found")
                webhook_secret = row["webhook_secret"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get webhook secret: {e}")
        raise HTTPException(status_code=500, detail="Database error")
        
    # Validation logic requires raw body
    body_bytes = await request.body()
    expected_mac = hmac.new(webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
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
    
    # We need repo URL
    repo_url = payload.get("repository", {}).get("clone_url")
    if not repo_url:
        raise HTTPException(status_code=400, detail="Missing repository clone_url")
        
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
                    raise HTTPException(status_code=400, detail="Project has no existing deployments to inherit configuration from")
                
                if last_deploy["repo_url"] != repo_url:
                    raise HTTPException(status_code=403, detail="Webhook repository does not match project's repository")
                    
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
        logger.error(f"Failed to process webhook DB insert for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process webhook")

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
        })
    except Exception as e:
        logger.error(f"Failed to enqueue webhook deployment {deployment_id}: {e}")
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
        raise HTTPException(status_code=500, detail="Failed to enqueue webhook deployment")
        
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
        raise HTTPException(status_code=500, detail="Server configuration error")

    body_bytes = await request.body()
    expected_mac = hmac.new(app_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
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
        raise HTTPException(status_code=400, detail="Missing repository URL in payload")
        
    # Find matching project
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # Find the most recently updated project that uses this repo
                cur.execute(
                    """
                    SELECT project_id, port, repo_url 
                    FROM deployments 
                    WHERE repo_url = %s OR repo_url = %s 
                    ORDER BY updated_at DESC LIMIT 1;
                    """,
                    (repo_url, html_url)
                )
                last_deploy = cur.fetchone()
                
                if not last_deploy:
                    logger.info(f"Ignored push event for {repo_url} - no matching ShipZen project found.")
                    return JSONResponse(status_code=200, content={"message": "No matching project, event ignored"})
                
                project_id = last_deploy["project_id"]
                port = last_deploy["port"]
                matched_repo_url = last_deploy["repo_url"]
                
    except Exception as e:
        logger.error(f"Failed to lookup project for github app webhook: {e}")
        raise HTTPException(status_code=500, detail="Database error during project lookup")
        
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
        logger.error(f"Failed to process webhook DB insert for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process webhook")

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
        })
    except Exception as e:
        logger.error(f"Failed to enqueue webhook deployment {deployment_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to enqueue webhook deployment")
        
    log_audit_event(
        project_id=project_id,
        user_id="github-app",
        action="WEBHOOK_DEPLOY",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"repo_url": matched_repo_url, "branch": branch, "via": "github-app"},
    )
    
    return {"message": "Deployment triggered via GitHub App", "deployment_id": deployment_id}

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
                cur.execute("SELECT id, email, role, created_at FROM users ORDER BY created_at DESC;")
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
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'admin' or 'user'.")
        
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING id;", (body.role, user_id))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="User not found")
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

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_project_or_404(project_id: str, current_user: User) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT * FROM projects WHERE id = %s;", (project_id,))
                row = cur.fetchone()
    except Exception as e:
        logger.error(f"DB error fetching project {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    if not row:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        
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
        raise HTTPException(status_code=404, detail=f"Deployment '{deployment_id}' not found")
    return dict(row)


def _serialize(obj: dict) -> dict:
    """Convert non-JSON-serializable types (datetime) to strings."""
    return {
        k: v.isoformat() if hasattr(v, "isoformat") else v
        for k, v in obj.items()
    }
