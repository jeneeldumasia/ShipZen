import redis
import time
import logging
import json
import os
import subprocess
import shutil
import uuid
import boto3
import base64
import signal
import yaml
from concurrent.futures import ThreadPoolExecutor
from kubernetes import client, config as k8s_config, watch
from kubernetes.client.rest import ApiException

from config import config
from queue_client import QueueClient
from state_machine import StateMachine, DeploymentState
from builder import DockerfileBuilder, RailpackBuilder, BuildpackBuilder
from metrics import (
    start_metrics_server,
    shipzen_build_duration_seconds,
    shipzen_queue_latency_seconds,
    shipzen_retry_total,
    shipzen_deployment_failure_total,
    shipzen_dlq_depth,
    shipzen_deployments_total
)

def get_github_app_token(repo_url: str) -> str:
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if not app_id or not private_key or not repo_url.startswith("https://github.com/"):
        return None
    
    try:
        # Parse owner/repo from URL
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        import jwt
        import requests
        
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": app_id
        }
        
        # Format the private key if it was passed without newlines
        if "\\n" in private_key:
            private_key = private_key.replace("\\n", "\n")
            
        encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")
        
        # 1. Get Installation ID for this repo
        headers = {
            "Authorization": f"Bearer {encoded_jwt}",
            "Accept": "application/vnd.github.v3+json"
        }
        resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/installation", headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Could not find GitHub App installation for {owner}/{repo}: {resp.status_code} {resp.text}")
            return None
            
        installation_id = resp.json()["id"]
        
        # 2. Create Installation Access Token
        token_resp = requests.post(f"https://api.github.com/app/installations/{installation_id}/access_tokens", headers=headers, timeout=10)
        if token_resp.status_code != 201:
            logger.warning(f"Failed to create GitHub App installation token: {token_resp.status_code} {token_resp.text}")
            return None
            
        return token_resp.json()["token"]
    except Exception as e:
        logger.error(f"Error fetching GitHub App token: {e}")
        return None

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('worker')

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

batch_v1 = client.BatchV1Api()
core_v1 = client.CoreV1Api()
s3 = boto3.client('s3')

S3_LOG_BUCKET = os.environ.get("S3_LOG_BUCKET", "")

# Limit concurrent monitoring threads to prevent unbounded thread exhaustion
import threading
# MED-07 Fix: Reduce MAX_WORKERS from 200 to 20 to match DB pool size and prevent OOM
MAX_WORKERS = 20
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_semaphore = threading.Semaphore(MAX_WORKERS)

# PERF-04 Fix: Shared module-level Redis client
_redis_client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, password=config.REDIS_PASSWORD)

from worker.database import get_db_connection

def record_build(deployment_id: str, s3_key: str, status: str):
    build_id = str(uuid.uuid4())
    if not S3_LOG_BUCKET:
        logger.warning(
            f"S3_LOG_BUCKET not set — skipping build record for {deployment_id}")
        return
    s3_uri = f"s3://{S3_LOG_BUCKET}/{s3_key}"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO builds (build_id, deployment_id, s3_log_uri, status)
                    VALUES (%s, %s, %s, %s);
                """, (build_id, deployment_id, s3_uri, status))
    except Exception as e:
        logger.error(f"Failed to record build for {deployment_id}: {e}")


def monitor_job(job_name: str, deployment_id: str, image_name: str, state_machine: StateMachine, builder_type: str = "unknown", project_id: str = "unknown", queue: QueueClient = None, message_id: str = None):
    """Monitors the Kubernetes Job, streams logs to Redis, and finalizes the deployment."""
    logger.info(f"Monitoring Job {job_name} for deployment {deployment_id}")
    r = _redis_client
    s3_log_key = f"logs/{deployment_id}/build.log"
    build_start_time = time.time()

    try:
        w = watch.Watch()
        pod_name = None

        # Wait for Pod to exist
        for event in w.stream(core_v1.list_namespaced_pod, namespace="shipzen-build", label_selector=f"job-name={job_name}", timeout_seconds=300):
            pod = event['object']
            status = pod.status.phase

            if status == "Pending":
                r.publish(f"shipzen:status:{deployment_id}", json.dumps(
                    {"state": "Queued", "last_error": None}))
            elif status in ["Running", "Succeeded", "Failed"]:
                pod_name = pod.metadata.name
                w.stop()
                break

        if not pod_name:
            raise Exception("Timed out waiting for Pod to be created")

        state_machine.update_state(deployment_id, DeploymentState.BUILDING)

        # Wait for container to start generating logs (sometimes there's a slight delay after phase=Running)
        time.sleep(2)

        # Stream Logs
        stdout_chunks = []
        try:
            log_stream = core_v1.read_namespaced_pod_log(
                name=pod_name, namespace="shipzen-build", follow=True, _preload_content=False,
                container=pod.spec.containers[0].name
            )
            for line in log_stream:
                stdout_chunks.append(line)
                try:
                    r.publish(f"shipzen:logs:{deployment_id}", line.decode(
                        'utf-8', errors='replace'))
                except Exception:
                    pass
        except ApiException as e:
            logger.warning(f"Error reading pod logs: {e}")

        # Wait for Job to complete using Watch API
        job_succeeded = False
        job_w = watch.Watch()
        try:
            for event in job_w.stream(batch_v1.list_namespaced_job, namespace="shipzen-build", field_selector=f"metadata.name={job_name}", timeout_seconds=3600):
                job = event['object']
                if job.status.succeeded and job.status.succeeded >= 1:
                    job_succeeded = True
                    break
                if job.status.failed and job.status.failed >= 1:
                    break
        finally:
            job_w.stop()

        # Upload logs to S3
        stdout_bytes = b''.join(stdout_chunks)
        try:
            if S3_LOG_BUCKET:
                import io
                s3.upload_fileobj(io.BytesIO(stdout_bytes),
                                  S3_LOG_BUCKET, s3_log_key)
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")

        # Observe build duration
        build_duration = time.time() - build_start_time
        shipzen_build_duration_seconds.labels(
            project_id=project_id, builder_type=builder_type).observe(build_duration)

        if job_succeeded:
            logger.info(
                f"Build {deployment_id} successful. Checking port/ECR...")

            # Fix 7: ecr variable used out of scope, move to before crane block
            ecr = boto3.client('ecr', region_name=os.getenv(
                "AWS_REGION", "us-east-1"))
            # Dynamic Port Detection via Crane
            try:
                auth_data = ecr.get_authorization_token()[
                    'authorizationData'][0]
                token = base64.b64decode(
                    auth_data['authorizationToken']).decode('utf-8')
                username, password = token.split(':')
                registry_url = auth_data['proxyEndpoint'].replace(
                    'https://', '')
                subprocess.run(["crane", "auth", "login", registry_url, "-u",
                               username, "-p", password], check=True, capture_output=True)

                crane_out = subprocess.check_output(
                    ["crane", "config", image_name], text=True)
                config_json = json.loads(crane_out)
                exposed_ports = config_json.get(
                    "config", {}).get("ExposedPorts", {})

                if exposed_ports:
                    first_port = list(exposed_ports.keys())[0].split('/')[0]
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;", (int(
                                first_port), deployment_id))
            except Exception as e:
                logger.warning(f"Failed to extract exposed port: {e}")

            # ECR Image Scanning Gate
            try:
                registry_and_repo, image_tag = image_name.rsplit(':', 1)
                repo_name = registry_and_repo.split('/', 1)[1]

                scan_status = "IN_PROGRESS"
                attempts = 0
                while scan_status in ("IN_PROGRESS", "PENDING") and attempts < 12:
                    time.sleep(5)
                    attempts += 1
                    res = ecr.describe_image_scan_findings(
                        repositoryName=repo_name, imageId={'imageTag': image_tag})
                    scan_status = res.get('imageScanStatus', {}).get(
                        'status', 'FAILED')

                if scan_status == "COMPLETE":
                    findings = res.get('imageScanFindings', {}).get(
                        'findingSeverityCounts', {})
                    fail_on = os.getenv("IMAGE_SCAN_FAIL_ON", "CRITICAL")
                    if findings.get(fail_on, 0) > 0:
                        raise Exception(
                            f"Image scan: {fail_on} vulnerability found")
            except Exception as e:
                logger.error(f"Image scan failed: {e}")
                record_build(deployment_id, s3_log_key, "Failed")
                shipzen_deployment_failure_total.inc()
                shipzen_deployments_total.labels(state="Failed", project_id=project_id).inc()
                state_machine.update_state(deployment_id, "Failed", str(e))
                return

            record_build(deployment_id, s3_log_key, "Success")
            state_machine.update_state(deployment_id, "Deploying")

        else:
            logger.error(f"Job {job_name} failed.")
            record_build(deployment_id, s3_log_key, "Failed")
            shipzen_deployment_failure_total.inc()
            shipzen_deployments_total.labels(state="Failed", project_id=project_id).inc()
            state_machine.update_state(
                deployment_id, "Failed", "Build step failed.")

    except Exception as e:
        logger.error(f"Error monitoring job {job_name}: {e}")
        record_build(deployment_id, s3_log_key, "Failed")
        shipzen_deployment_failure_total.inc()
        shipzen_deployments_total.labels(state="Failed", project_id=project_id).inc()
        state_machine.update_state(deployment_id, "Failed", str(e))
    finally:
        # Cleanup Job
        try:
            batch_v1.delete_namespaced_job(
                job_name, "shipzen-build", propagation_policy="Background")
        except Exception:
            pass
        pass


def process_message(queue: QueueClient, state_machine: StateMachine, message_id: str, data: dict):
    deployment_id = data.get("deployment_id")
    repo_url = data.get("repo_url")
    branch = data.get("branch", "main")
    image_name = data.get("image_name")

    if not deployment_id or not repo_url or not image_name:
        queue.add_to_dlq(message_id, data)
        return
        
    # CRIT-01 Fix: Additional branch name validation at worker level
    import re
    if not re.match(r'^[a-zA-Z0-9_.\-/]{1,200}$', branch):
        logger.error(f"Invalid branch name received: {branch}")
        queue.add_to_dlq(message_id, data)
        return

    deployment = state_machine.get_deployment(deployment_id)
    if deployment and deployment.get("state") in [DeploymentState.BUILDING, DeploymentState.DEPLOYING, DeploymentState.RUNNING]:
        queue.ack_message(message_id)
        return

    # Fix 1: Skip building if this is a rollback, just advance state
    if data.get("is_rollback") == "true":
        logger.info(
            f"Deployment {deployment_id} is a rollback, skipping build.")
        state_machine.update_state(deployment_id, "Deploying")
        queue.ack_message(message_id)
        # HIGH-03 Fix: Removed _semaphore.release() from here because the finally block handles it
        return

    logger.info(f"Processing deployment {deployment_id}")
    shipzen_deployments_total.labels(state="Processing", project_id=deployment.get("project_id", "unknown") if deployment else "unknown").inc()

    # Calculate queue latency from Redis stream ID
    try:
        if isinstance(message_id, bytes):
            msg_id_str = message_id.decode("utf-8")
        else:
            msg_id_str = str(message_id)
        timestamp_ms = int(msg_id_str.split("-")[0])
        queue_latency = time.time() - (timestamp_ms / 1000.0)
        shipzen_queue_latency_seconds.observe(queue_latency)
    except Exception:
        pass

    # Fix 8: Workspace directory leaks on clone failure, moved creation inside try and cleanup to finally
    workspace = f"/tmp/workspace_{deployment_id}"
    # HIGH-11 Fix: Initialize before try block to prevent UnboundLocalError in finally
    github_secret_name = None
    try:
        clone_url = repo_url
        if repo_url.startswith("https://github.com/"):
            token = get_github_app_token(repo_url)
            if token:
                clone_url = repo_url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
                github_secret_name = f"git-token-{deployment_id[:8]}"
                secret = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=github_secret_name, namespace="shipzen-build"),
                    string_data={"GITHUB_TOKEN": token}
                )
                try:
                    core_v1.create_namespaced_secret(namespace="shipzen-build", body=secret)
                except ApiException as e:
                    if e.status == 409:
                        core_v1.replace_namespaced_secret(name=github_secret_name, namespace="shipzen-build", body=secret)
                    else:
                        raise

        # Shallow clone to detect builder (worker local)
        os.makedirs(workspace, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", "--branch",
                       branch, clone_url, workspace], check=True, timeout=120)
        subprocess.run(["git", "sparse-checkout", "set", "shipzen.yaml", "Dockerfile", "Cargo.toml", "bun.lockb", "package.json"], cwd=workspace, check=True)

        # Check overrides
        overrides = {}
        config_path = os.path.join(workspace, "shipzen.yaml")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                cfg = yaml.safe_load(f)
                if cfg:
                    overrides = cfg
                    new_port = cfg.get("port")
                    new_health = cfg.get("health_check_path")
                    if new_port or new_health:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                if new_port and new_health:
                                    cur.execute("UPDATE deployments SET port = %s, health_check_path = %s WHERE deployment_id = %s;", (
                                        new_port, new_health, deployment_id))
                                elif new_port:
                                    cur.execute(
                                        "UPDATE deployments SET port = %s WHERE deployment_id = %s;", (new_port, deployment_id))
                                elif new_health:
                                    cur.execute(
                                        "UPDATE deployments SET health_check_path = %s WHERE deployment_id = %s;", (new_health, deployment_id))

        # SPA detection
        package_json_path = os.path.join(workspace, "package.json")
        if os.path.exists(package_json_path):
            if os.path.getsize(package_json_path) > 1024 * 1024:
                logger.warning(f"package.json too large to parse for {deployment_id}")
            else:
                try:
                    with open(package_json_path, 'r') as f:
                        pj = json.load(f)
                    scripts = pj.get("scripts", {})
                    deps = {**pj.get("dependencies", {}), **pj.get("devDependencies", {})}
                    if "start" not in scripts:
                        if any(m in deps for m in ["vite", "react-scripts", "vue", "svelte", "astro"]) or ("build" in scripts):
                            overrides["inject_server_js"] = True
                    if "build" in scripts:
                        overrides["bp_node_run_scripts"] = "build"
                except json.JSONDecodeError:
                    pass

        # Builder detection
        builders = [DockerfileBuilder(), RailpackBuilder(), BuildpackBuilder()]
        selected_builder = None
        for b in builders:
            if b.detect(workspace):
                selected_builder = b
                break

        if not selected_builder:
            raise Exception("No suitable builder found")

        # Ensure the per-project ECR repository exists before launching the build.
        # ECR does not auto-create repos on push — pack's ANALYZING phase will fail
        # with NAME_UNKNOWN if the repo doesn't exist.
        # CreateRepository is idempotent: we catch RepositoryAlreadyExistsException.
        try:
            registry_and_repo = image_name.rsplit(":", 1)[0]   # strip the tag
            repo_name = registry_and_repo.split(
                "/", 1)[1]     # strip the registry hostname
            ecr_client = boto3.client(
                "ecr", region_name=os.getenv("AWS_REGION", "us-east-1"))
            ecr_client.create_repository(
                repositoryName=repo_name,
                imageTagMutability="IMMUTABLE",
                imageScanningConfiguration={"scanOnPush": True},
            )
            logger.info(f"Created ECR repository: {repo_name}")
        except ecr_client.exceptions.RepositoryAlreadyExistsException:
            pass  # Already exists — nothing to do
        except Exception as e:
            logger.warning(f"Could not ensure ECR repository exists: {e}")
            # Non-fatal — the build may still succeed if the repo was created externally

        if github_secret_name:
            overrides["github_secret_name"] = github_secret_name

        # Pass repo_url to the builder, not clone_url, so the K8s manifest doesn't get the plaintext token
        manifest = selected_builder.generate_job_manifest(
            deployment_id, repo_url, branch, image_name, overrides)
        job_name = manifest["metadata"]["name"]

        # Create Job
        try:
            batch_v1.create_namespaced_job(
                namespace="shipzen-build", body=manifest)
            logger.info(f"Created Job {job_name} for deployment {deployment_id}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Job {job_name} already exists (XAUTOCLAIM redelivery). Continuing to monitor.")
            else:
                raise Exception(f"Kubernetes Job creation failed (HTTP {e.status}): {e.reason}. "
                                f"Ensure the 'shipzen-build' namespace exists and the worker ServiceAccount has batch/jobs create permission.")

        # Call monitor_job synchronously in this thread
        builder_type = selected_builder.name if hasattr(
            selected_builder, 'name') else type(selected_builder).__name__
        project_id_db = deployment.get(
            "project_id", "unknown") if deployment else "unknown"
        monitor_job(job_name, deployment_id, image_name, state_machine, builder_type, project_id_db)
        queue.ack_message(message_id)

    except Exception as e:
        logger.error(f"Error processing {deployment_id}: {e}")
        # Persist the actual error so the UI can display it rather than the
        # generic "Build step failed." message
        state_machine.update_state(deployment_id, "Failed", str(e))
        shipzen_deployment_failure_total.inc()
        shipzen_deployments_total.labels(state="Failed", project_id=deployment.get("project_id", "unknown") if deployment else "unknown").inc()
        queue.add_to_dlq(message_id, data)
        shipzen_dlq_depth.inc()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if github_secret_name:
            try:
                core_v1.delete_namespaced_secret(name=github_secret_name, namespace="shipzen-build")
            except Exception as e:
                logger.warning(f"Failed to delete GitHub token secret {github_secret_name}: {e}")
        _semaphore.release()


def main():
    # HIGH-10 Fix: Graceful shutdown flag
    _shutdown = False

    def handle_sigterm(signum, frame):
        nonlocal _shutdown
        logger.info("Received SIGTERM, initiating graceful shutdown...")
        _shutdown = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    start_metrics_server(port=8000)
    queue = QueueClient()
    state_machine = StateMachine()

    logger.info(
        f"Worker {config.CONSUMER_NAME} started. Listening on stream {config.STREAM_NAME}")

    # REL-02 Fix: Track backoff state
    error_backoff = 2

    while not _shutdown:
        try:
            claimed = queue.recover_pending_messages()
            if claimed:
                for msg_id, data in claimed:
                    shipzen_retry_total.inc()
                    _semaphore.acquire()
                    _executor.submit(process_message, queue, state_machine, msg_id, data)

            messages = queue.get_messages(count=5, block_ms=2000)
            if messages:
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        _semaphore.acquire()
                        _executor.submit(process_message, queue, state_machine, msg_id, data)
            
            # Reset backoff on success
            error_backoff = 2
        except Exception:
            logger.exception("Queue read error")
            time.sleep(error_backoff)
            error_backoff = min(60, error_backoff * 2)  # Exponential backoff up to 60s
            
    logger.info("Worker main loop exited. Waiting for running threads to finish...")
    _executor.shutdown(wait=True, cancel_futures=False)
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
