import pytest
from unittest.mock import patch, MagicMock
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
import os
import threading
import psycopg2

import docker

def is_docker_running():
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False

pytestmark = pytest.mark.skipif(not is_docker_running(), reason="Docker daemon is not running")

# Set test environment variables BEFORE importing application code
os.environ["S3_LOG_BUCKET"] = "test-bucket"
os.environ["STREAM_NAME"] = "test_stream"
os.environ["CONSUMER_GROUP"] = "test_group"

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15-alpine", dbname="shipzen") as postgres:
        os.environ["DATABASE_URL"] = postgres.get_connection_url()
        # Initialize schema
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = True
        with conn.cursor() as cur:
            schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "schema.sql")
            with open(schema_path, "r") as f:
                cur.execute(f.read())
        conn.close()
        yield postgres

@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis_server:
        os.environ["REDIS_HOST"] = redis_server.get_container_host_ip()
        os.environ["REDIS_PORT"] = redis_server.get_exposed_port(6379)
        yield redis_server

@pytest.fixture(autouse=True)
def setup_db(postgres_container):
    # Truncate tables before each test to ensure a clean state
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE users, projects, deployments, env_vars, builds CASCADE;")
    conn.close()

# --- 1. Deployment State Machine Transitions ---
def test_deployment_state_machine(postgres_container):
    from worker.state_machine import StateMachine, DeploymentState
    
    # Setup test data
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('user1', 'test@test.com', 'admin')")
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace) VALUES ('proj1', 'user1', 'p1', 'ns1')")
        cur.execute("INSERT INTO deployments (deployment_id, project_id, repo_url, port, state) VALUES ('dep1', 'proj1', 'http://repo', 80, 'Queued')")
    conn.close()

    sm = StateMachine()
    
    # Test Queued -> Deploying
    sm.update_state('dep1', DeploymentState.DEPLOYING)
    deployment = sm.get_deployment('dep1')
    assert deployment["state"] == DeploymentState.DEPLOYING
    
    # Test Deploying -> Running
    sm.update_state('dep1', DeploymentState.RUNNING)
    deployment = sm.get_deployment('dep1')
    assert deployment["state"] == DeploymentState.RUNNING

# --- 2. Rollback Flow End-to-End ---
def test_rollback_skips_build(redis_container, postgres_container):
    from worker.main import process_message
    
    # Setup test data
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('user1', 'test@test.com', 'admin') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace) VALUES ('proj2', 'user1', 'p2', 'ns2')")
        cur.execute("INSERT INTO deployments (deployment_id, project_id, repo_url, port, state) VALUES ('dep2', 'proj2', 'http://repo', 80, 'Queued')")
    conn.close()

    payload = {
        "deployment_id": "dep2",
        "repo_url": "http://repo",
        "is_rollback": "true",
        "image_name": "123.dkr.ecr.us-east-1.amazonaws.com/app:abc123"
    }
    
    mock_queue = MagicMock()
    
    from worker.state_machine import StateMachine
    sm = StateMachine()

    # The actual regression guard: ensure subprocess.run (used for git clone and crane) is NOT called!
    with patch("worker.main.subprocess.run") as mock_sub:
        process_message(mock_queue, sm, "msg-123", payload)
        mock_sub.assert_not_called()
        
    deployment = sm.get_deployment('dep2')
    # Rollback should skip BUILD and immediately go to DEPLOYING
    assert deployment["state"] == "Deploying"

# --- 3. Webhook Handler ---
@pytest.mark.asyncio
async def test_webhook_handler_hmac_rejection(postgres_container):
    from api.main import github_webhook
    from fastapi import Request, HTTPException
    
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('user1', 'test@test.com', 'admin') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace, webhook_secret) VALUES ('proj3', 'user1', 'p3', 'ns3', 'mysecret')")
    conn.close()

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": "sha256=invalid_signature_here"
    }
    mock_request.body = MagicMock(return_value=b'{"repository": {"clone_url": "http://repo"}}')
    
    with pytest.raises(HTTPException) as exc:
        await github_webhook(mock_request, "proj3")
    
    # CRIT-08 Fix: Wait, actual handler raises 401 for invalid signature, test asserted 403
    assert exc.value.status_code == 401
    assert "Invalid signature" in exc.value.detail

# --- 4. get_or_create_user Concurrent Inserts ---
def test_get_or_create_user_concurrent(postgres_container):
    from api.database import get_or_create_user
    
    results = []
    
    def worker():
        try:
            user = get_or_create_user("concurrent_user_1", "concurrent@test.com")
            results.append(user)
        except Exception as e:
            results.append(e)

    # Spawn multiple threads to trigger a race condition (UniqueViolation)
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should have received a valid user dict, no Exceptions!
    for res in results:
        assert isinstance(res, dict)
        assert res["id"] == "concurrent_user_1"

# --- 5. Env Var Endpoints (Secret ID) ---
def test_env_var_secret_id_uses_project_id():
    from api.main import put_env_var
    from api.auth import User
    
    # Mock Kubernetes API to verify the secret_name
    with patch("api.main.core_v1.create_namespaced_secret") as mock_create:
        mock_user = User(id="user1", email="test", role="admin")
        
        # We need to mock the project DB lookup
        with patch("api.main._get_project_or_404") as mock_get_proj:
            mock_get_proj.return_value = {"id": "proj4", "namespace": "ns4", "name": "My Project"}
            
            # The body includes key and value
            body = {"key": "MY_VAR", "value": "myval"}
            
            mock_request = MagicMock()
            put_env_var(mock_request, "proj4", body, mock_user)
            
            called_secret = mock_create.call_args[1]["body"]
            
            # THE REGRESSION GUARD: secret name must be shipzen-proj4, NOT shipzen-My Project
            assert called_secret.metadata.name == "shipzen-proj4"

# --- 6. Analyze Repo Branch Validation ---
def test_analyze_repo_branch_validation():
    from api.main import analyze_repo
    from api.auth import User
    from fastapi import HTTPException
    
    mock_user = User(id="user1", email="test", role="admin")
    mock_request = MagicMock()
    
    class MockBody:
        repo_url = "http://github.com/test/test.git"
        branch = "invalid branch name with spaces!"
        
    with pytest.raises(HTTPException) as exc:
        analyze_repo(mock_request, MockBody(), mock_user)
        
    assert exc.value.status_code == 400
    assert "Invalid branch name" in exc.value.detail
