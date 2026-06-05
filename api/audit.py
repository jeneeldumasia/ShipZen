import json
import logging
from database import get_connection
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)

# Fix #9.3: hard cap on audit log query size to prevent runaway queries
MAX_AUDIT_LIMIT = 500


def log_audit_event(
    project_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict,
):
    """
    Appends an event to the audit_logs table.
    This table is logically append-only.

    Fix #3.4: exceptions are caught and logged rather than propagated.
    Audit logging is a side effect — a DB failure here must not crash the
    originating API request.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_logs
                        (project_id, user_id, action, resource_type, resource_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (project_id, user_id, action, resource_type, resource_id, json.dumps(details)),
                )
        logger.info(f"Audit event logged: {action} on {resource_type} {resource_id} by {user_id}")
    except Exception as e:
        # Log and swallow — never let audit logging break the caller
        logger.error(f"Failed to write audit event ({action} / {resource_id}): {e}")


def get_audit_logs(project_id: str = None, user_id: str = None, limit: int = 50):
    """
    Queries the append-only audit log by project or user.

    Fix #9.3: limit is capped at MAX_AUDIT_LIMIT (500) to prevent a caller
    passing limit=1000000 from issuing a runaway query.
    """
    limit = min(int(limit), MAX_AUDIT_LIMIT)

    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []

    if project_id:
        query += " AND project_id = %s"
        params.append(project_id)
    if user_id:
        query += " AND user_id = %s"
        params.append(user_id)

    query += " ORDER BY timestamp DESC LIMIT %s;"
    params.append(limit)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, tuple(params))
            return [dict(row) for row in cur.fetchall()]
