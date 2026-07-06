import threading
from auth import get_current_user, User
from fastapi import Depends, HTTPException
from psycopg2.pool import ThreadedConnectionPool
import os
import psycopg2
from psycopg2.extras import DictCursor
import logging

logger = logging.getLogger(__name__)

# Fix #20: raise immediately on missing env var rather than silently falling
# back to postgres:postgres which will never connect inside the cluster.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


db_pool = None
_db_pool_lock = threading.Lock()


class PooledConnectionWrapper:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def __enter__(self):
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._pool.putconn(self._conn)
            self._conn = None  # Prevent double put

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._conn:
            self._pool.putconn(self._conn)
            self._conn = None


def get_connection():
    global db_pool
    if db_pool is None:                     # fast path — no lock once initialised
        with _db_pool_lock:
            if db_pool is None:             # double-checked locking
                db_pool = ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
    conn = db_pool.getconn()
    return PooledConnectionWrapper(conn, db_pool)


def get_deployments_paginated(project_id: str, limit: int = 20, cursor_updated_at: str = None):
    """
    Keyset pagination (cursor-based) — avoids OFFSET degradation on large tables.
    """
    query = """
        SELECT deployment_id, state, updated_at
        FROM deployments
        WHERE project_id = %s
    """
    params = [project_id]

    if cursor_updated_at:
        query += " AND updated_at < %s"
        params.append(cursor_updated_at)

    query += " ORDER BY updated_at DESC LIMIT %s;"
    params.append(limit)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, tuple(params))
            return [dict(row) for row in cur.fetchall()]


def get_or_create_user(user_id: str, email: str = None) -> dict:
    """Gets a user by ID, or creates them. The first user created gets the 'admin' role."""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, role FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()
                if user:
                    return dict(user)

                # Fix 11: get_or_create_user has a TOCTOU race condition
                # Use an advisory lock to prevent race condition during initial admin creation
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('users_insert_lock'));")
                cur.execute("SELECT COUNT(*) FROM users")
                count = cur.fetchone()[0]
                role = 'admin' if count == 0 else 'user'

                cur.execute(
                    "INSERT INTO users (id, email, role) VALUES (%s, %s, %s) RETURNING id, role",
                    (user_id, email, role)
                )
                new_user = cur.fetchone()
                return dict(new_user)
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT id, role FROM users WHERE id = %s", (user_id,))
                return dict(cur.fetchone())
        except Exception as e:
            logger.error(f"Failed to get_or_create_user: {e}")
            raise


def enforce_retention_policy():
    """
    Retention Policy: delete failed builds older than 30 days,
    successful builds older than 90 days.

    Fix #3.5: was mixing manual conn.commit() with the psycopg2 context
    manager, leaving no rollback path on failure. Now uses an explicit
    transaction block with proper commit/rollback.
    """
    logger.info("Running retention policy cleanup...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM builds
                WHERE (status = 'Failed'  AND completed_at < NOW() - INTERVAL '30 days')
                   OR (status = 'Success' AND completed_at < NOW() - INTERVAL '90 days');
            """)
            deleted = cur.rowcount
        conn.commit()
        logger.info(f"Retention policy applied. Deleted {deleted} old builds.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Retention policy failed, rolled back: {e}")
        raise
    finally:
        conn.close()


def init_db():
    """Run schema.sql to ensure tables exist on startup."""
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
            logger.info("Database schema initialized successfully.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to execute schema.sql: {e}")
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to read/initialize database schema: {e}")


def verify_project_access(
    project_id: str,
    current_user: User = Depends(get_current_user)
) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            if current_user.role == 'admin':
                cur.execute(
                    "SELECT * FROM projects WHERE id = %s AND deleted_at IS NULL", (project_id,))
                project = cur.fetchone()
                if not project:
                    raise HTTPException(
                        status_code=404, detail="Project not found")
                return dict(project)
            else:
                cur.execute("""
                    SELECT p.* FROM projects p
                    JOIN project_members pm ON pm.project_id = p.id
                    WHERE p.id = %s AND pm.user_id = %s AND p.deleted_at IS NULL;
                """, (project_id, current_user.user_id))
                project = cur.fetchone()
                if not project:
                    raise HTTPException(
                        status_code=403, detail="You do not have access to this project")
                return dict(project)
