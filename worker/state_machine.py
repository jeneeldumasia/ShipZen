import json
import redis
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


from worker.database import get_db_connection

class StateMachine:
    def __init__(self):
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            self._redis = redis.Redis(
                host=config.REDIS_HOST, port=config.REDIS_PORT, password=config.REDIS_PASSWORD)
        return self._redis

    def update_state(self, deployment_id: str, new_state: str, error_msg: str = None):
        """
        Idempotent state update.
        Kubernetes state is not authoritative; PostgreSQL is.
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE deployments
                        SET state       = %s,
                            updated_at  = %s,
                            last_error  = %s
                        WHERE deployment_id = %s;
                    """, (new_state, datetime.now(timezone.utc), error_msg, deployment_id))
                    if cur.rowcount == 0:
                        logger.warning(
                            f"Deployment {deployment_id} not found in DB when transitioning to {new_state}")

            # Publish state update to Redis
            try:
                payload = json.dumps(
                    {"state": new_state, "last_error": error_msg})
                self._get_redis().publish(
                    f"shipzen:status:{deployment_id}", payload)
            except Exception as e:
                logger.warning(f"Failed to publish status to Redis: {e}")

            logger.info(
                f"Deployment {deployment_id} transition -> {new_state}")
        except psycopg2.OperationalError as e:
            logger.warning(f"DB connection dropped during update_state: {e}")
            raise

    def get_deployment(self, deployment_id: str):
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM deployments WHERE deployment_id = %s;", (deployment_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        except psycopg2.OperationalError as e:
            logger.warning(f"DB connection dropped during get_deployment: {e}")
            raise
