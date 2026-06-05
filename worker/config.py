import os


class Config:
    REDIS_HOST = os.getenv("REDIS_HOST", "redis-master.deployhub-system.svc.cluster.local")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

    # Fix #20: raise on missing DATABASE_URL rather than silently falling back
    # to hardcoded postgres:postgres, which will never connect in-cluster.
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    STREAM_NAME = os.getenv("STREAM_NAME", "deploy_stream")
    CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "worker_group")
    CONSUMER_NAME = os.getenv("HOSTNAME", "worker-1")  # Unique per pod via downward API

    # Fix #7: builder queue name in one place so worker and builder stay in sync.
    # Set BUILDER_QUEUE_NAME env var if you rename the stream.
    BUILDER_QUEUE_NAME = os.getenv("BUILDER_QUEUE_NAME", "builder_queue")

    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    PENDING_MESSAGE_TIMEOUT_MS = int(os.getenv("PENDING_MESSAGE_TIMEOUT_MS", "300000"))  # 5 minutes


config = Config()
