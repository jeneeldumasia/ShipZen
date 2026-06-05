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


def get_connection():
    return psycopg2.connect(DATABASE_URL)


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
