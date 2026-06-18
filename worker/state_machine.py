import logging
import psycopg2
from psycopg2.extras import DictCursor
from config import config
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DeploymentState:
    QUEUED = "Queued"
    BUILDING = "Building"
    DEPLOYING = "Deploying"
    VERIFYING = "Verifying"
    RUNNING = "Running"
    RETRY = "Retry"
    DLQ = "DLQ"


class StateMachine:
    def __init__(self):
        # Fix #4: connection is created lazily via _get_conn() which reconnects
        # on any broken-pipe / interface-error rather than using one persistent
        # connection for the entire process lifetime.
        self._conn = None
        # Fix #3: removed _ensure_table(). The canonical schema (api/schema.sql)
        # owns the deployments table definition. The worker creating its own
        # truncated 4-column version caused a schema conflict where the
        # controller's queries for project_id, image_uri, replicas, port would
        # fail with UndefinedColumn. Schema bootstrapping happens at cluster
        # init, not inside the worker.

    def _get_conn(self):
        """
        Returns a live connection, reconnecting automatically if the previous
        one was closed by the server (idle timeout, DB restart, network blip).
        """
        if self._conn is None or self._conn.closed:
            logger.info("Opening new DB connection...")
            self._conn = psycopg2.connect(config.DATABASE_URL)
            self._conn.autocommit = True
        else:
            # Cheap liveness check — raises if the connection is broken
            try:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except psycopg2.Error:
                logger.warning("DB connection stale, reconnecting...")
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = psycopg2.connect(config.DATABASE_URL)
                self._conn.autocommit = True
        return self._conn

    def update_state(self, deployment_id: str, new_state: str, error_msg: str = None):
        """
        Idempotent state update.
        Kubernetes state is not authoritative; PostgreSQL is.
        """
        for attempt in range(2):
            try:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE deployments
                        SET state       = %s,
                            updated_at  = %s,
                            last_error  = %s
                        WHERE deployment_id = %s;
                    """, (new_state, datetime.now(timezone.utc), error_msg, deployment_id))
                    if cur.rowcount == 0:
                        logger.warning(f"Deployment {deployment_id} not found in DB when transitioning to {new_state}")
                # Fix #24: was print(), now uses structured logger
                logger.info(f"Deployment {deployment_id} transition -> {new_state}")
                break
            except psycopg2.OperationalError as e:
                if attempt == 0:
                    logger.warning(f"DB connection dropped during update_state, retrying: {e}")
                    if self._conn:
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                    self._conn = None
                else:
                    raise

    def get_deployment(self, deployment_id: str):
        for attempt in range(2):
            try:
                conn = self._get_conn()
                with conn.cursor(cursor_factory=DictCursor) as cur:
                    cur.execute("SELECT * FROM deployments WHERE deployment_id = %s;", (deployment_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            except psycopg2.OperationalError as e:
                if attempt == 0:
                    logger.warning(f"DB connection dropped during get_deployment, retrying: {e}")
                    if self._conn:
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                    self._conn = None
                else:
                    raise
