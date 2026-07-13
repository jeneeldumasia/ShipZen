import os
import threading
from psycopg2.pool import ThreadedConnectionPool

_db_pool = None
_pool_lock = threading.Lock()

class PooledConnectionWrapper:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._conn.autocommit = True
        
    def __enter__(self):
        return self._conn
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            self._pool.putconn(self._conn)
            self._conn = None

def get_db_connection():
    global _db_pool
    if _db_pool is None:
        with _pool_lock:
            if _db_pool is None:
                _db_pool = ThreadedConnectionPool(1, 20, os.environ.get("DATABASE_URL", ""))
                
    return PooledConnectionWrapper(_db_pool.getconn(), _db_pool)
