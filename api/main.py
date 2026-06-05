"""
DeployHub API Server — Phase 16
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
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from database import get_connection
from audit import log_audit_event
from auth import get_current_user, User

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('api')

# ── Config ────────────────────────────────────────────────────────────────────

REDIS_HOST  = os.getenv("REDIS_HOST", "redis-master.deployhub-system.svc.cluster.local")
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

app = FastAPI(
    title="DeployHub API",
    description="Internal Developer Platform — deploy any repo to Kubernetes",
    version="1.0.0",
)

# CORS — allow the Next.js dev server and any deployed UI origin.
# In production, replace "*" with the actual UI domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
def healthz():
    """Liveness probe endpoint. Always returns 200."""
    return {"status": "ok"}

# ── Projects ──────────────────────────────────────────────────────────────────

@app.post("/projects", status_code=201, tags=["Projects"])
def create_project(body: CreateProjectRequest, current_user: User = Depends(get_current_user)):
    """
    Create a new project. The controller picks up status=Provisioning
    and creates the tenant namespace + RBAC in Kubernetes.
    """
    project_id = str(uuid.uuid4())
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO projects (id, owner_id, name, namespace, status)
                    VALUES (%s, %s, %s, %s, 'Provisioning')
                    RETURNING *;
                    """,
                    (project_id, current_user.user_id, body.name, body.namespace),
                )
                project = dict(cur.fetchone())
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
def list_projects(current_user: User = Depends(get_current_user)):
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
def get_project(project_id: str, current_user: User = Depends(get_current_user)):
    """Get a single project by ID."""
    project = _get_project_or_404(project_id, current_user)
    return _serialize(project)


@app.delete("/projects/{project_id}", status_code=202, tags=["Projects"])
def delete_project(project_id: str, current_user: User = Depends(get_current_user)):
    """
    Soft-delete a project — sets status to Terminating.
    The controller will delete the Kubernetes namespace and then
    hard-delete the row once the namespace is gone.
    """
    _get_project_or_404(project_id, current_user)
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

# ── Deployments ───────────────────────────────────────────────────────────────

@app.post("/projects/{project_id}/deployments", status_code=202, tags=["Deployments"])
def create_deployment(project_id: str, body: CreateDeploymentRequest, current_user: User = Depends(get_current_user)):
    """
    Submit a deployment request. Only a repo URL is required.
    - The platform generates the image URI automatically from ECR_REPOSITORY_URL.
    - Scaling is handled by Karpenter/KEDA — the user does not set replicas.
    - Port defaults to 8080; override only if your app listens elsewhere.
    """
    project = _get_project_or_404(project_id, current_user)
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
        image_uri = f"{ECR_REPOSITORY_URL}:{deployment_id}"
    else:
        # Local dev / testing fallback — no ECR configured
        image_uri = f"local/deployhub-builds:{deployment_id}"

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


@app.get("/projects/{project_id}/deployments", tags=["Deployments"])
def list_deployments(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="updated_at cursor for keyset pagination"),
    current_user: User = Depends(get_current_user),
):
    """
    List deployments for a project with keyset pagination.
    Pass the `updated_at` value of the last item as `cursor` to get the next page.
    """
    _get_project_or_404(project_id, current_user)

    query = """
        SELECT deployment_id, project_id, repo_url, image_uri, replicas, port, state, updated_at, last_error
        FROM deployments
        WHERE project_id = %s
    """
    params = [project_id]

    if cursor:
        query += " AND updated_at < %s"
        params.append(cursor)

    query += " ORDER BY updated_at DESC LIMIT %s;"
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
def get_deployment(project_id: str, deployment_id: str, current_user: User = Depends(get_current_user)):
    """Get a single deployment's current state and last error."""
    _get_project_or_404(project_id, current_user)
    return _serialize(_get_deployment_or_404(project_id, deployment_id))

# ── Builds ────────────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/deployments/{deployment_id}/builds", tags=["Builds"])
def list_builds(project_id: str, deployment_id: str, current_user: User = Depends(get_current_user)):
    """List all builds for a deployment, most recent first."""
    _get_project_or_404(project_id, current_user)
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

# ── Audit ─────────────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/audit", tags=["Audit"])
def get_audit_logs(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """List audit log entries for a project."""
    _get_project_or_404(project_id, current_user)

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
