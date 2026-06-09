import io
import os
import re
import time
import uuid
import logging
import subprocess
import threading
import redis
import psycopg2
import boto3
import yaml
from prometheus_client import Histogram, start_http_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('builder')

deployhub_build_duration_seconds = Histogram(
    'deployhub_build_duration_seconds',
    'Build duration from clone to push',
    buckets=[30, 60, 120, 300, 600, 900]
)

REDIS_HOST    = os.getenv("REDIS_HOST", "redis-master.deployhub-system.svc.cluster.local")
REDIS_PORT    = int(os.getenv("REDIS_PORT", "6379"))
BUILDER_QUEUE = os.getenv("BUILDER_QUEUE_NAME", "builder_queue")   # Fix #7: matches config key
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "builder_group")
CONSUMER_NAME  = os.getenv("HOSTNAME", "builder-1")

# Fix #20: raise on missing DATABASE_URL instead of silently using a
# hardcoded credential that will never connect inside the cluster.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

S3_LOG_BUCKET = os.environ.get("S3_LOG_BUCKET", "")
if not S3_LOG_BUCKET:
    raise RuntimeError("S3_LOG_BUCKET environment variable is not set")

# Fix #6: allowlist of repo URL schemes.
# Only https:// and ssh git@ URLs are permitted. file://, arbitrary SSH
# hosts via --upload-pack, and other schemes are rejected before any shell
# call is made.
_REPO_URL_ALLOWLIST = re.compile(
    r'^(https://[a-zA-Z0-9._/:\-@]+\.git'   # https://host/path.git
    r'|https://[a-zA-Z0-9._/:\-@]+'          # https://host/path (no .git)
    r'|git@[a-zA-Z0-9._\-]+:[a-zA-Z0-9._/\-]+\.git)$'  # git@host:org/repo.git
)

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
s3 = boto3.client('s3')

try:
    r.xgroup_create(BUILDER_QUEUE, CONSUMER_GROUP, id='0', mkstream=True)
except redis.exceptions.ResponseError as e:
    if "BUSYGROUP" not in str(e):
        raise


def get_db_conn():
    """New connection per call. Builder pods are short-lived so this is fine;
    the overhead is negligible compared to a build that takes minutes."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def update_db_state(deployment_id: str, state: str, error_msg: str = None):
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE deployments
                SET state = %s, last_error = %s, updated_at = NOW()
                WHERE deployment_id = %s;
            """, (state, error_msg, deployment_id))
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update PostgreSQL state for {deployment_id}: {e}")


def record_build(deployment_id: str, s3_key: str, status: str):
    build_id = str(uuid.uuid4())
    s3_uri = f"s3://{S3_LOG_BUCKET}/{s3_key}"
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO builds (build_id, deployment_id, s3_log_uri, status)
                VALUES (%s, %s, %s, %s);
            """, (build_id, deployment_id, s3_uri, status))
        conn.close()
    except Exception as e:
        logger.error(f"Failed to record build for {deployment_id}: {e}")


def validate_message(deployment_id, repo_url, image_name):
    """Fix #3.2: validate all required fields before attempting a build."""
    if not deployment_id:
        raise ValueError("deployment_id is missing from message")
    if not repo_url:
        raise ValueError(f"repo_url is missing for deployment {deployment_id}")
    if not image_name:
        raise ValueError(f"image_name is missing for deployment {deployment_id}")

    # Fix #6: reject URLs that don't match the allowlist
    if not _REPO_URL_ALLOWLIST.match(repo_url):
        raise ValueError(
            f"repo_url '{repo_url}' does not match allowed schemes "
            f"(https:// or git@host:org/repo.git). Rejecting build."
        )


def run_build(deployment_id: str, repo_url: str, image_name: str):
    workspace = f"/workspace/{deployment_id}"
    os.makedirs(workspace, exist_ok=True)

    try:
        # Fix #3.1: git clone failure now records a failed build entry so
        # post-mortem debugging is possible even when the build never started.
        logger.info(f"Cloning {repo_url} into {workspace}")
        try:
            subprocess.run(["git", "clone", "--depth=1", repo_url, workspace], check=True)
        except subprocess.CalledProcessError as e:
            record_build(deployment_id, f"logs/{deployment_id}/build.log", "Failed")
            update_db_state(deployment_id, "Failed", f"git clone failed: {e}")
            return

        s3_log_key = f"logs/{deployment_id}/build.log"

        # Check for deployhub.yaml overrides
        config_path = os.path.join(workspace, "deployhub.yaml")
        pack_args = []
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                if config:
                    new_port = config.get("port")
                    new_health = config.get("health_check_path")
                    if new_port or new_health:
                        conn = get_db_conn()
                        with conn.cursor() as cur:
                            if new_port and new_health:
                                cur.execute("UPDATE deployments SET port = %s, health_check_path = %s WHERE deployment_id = %s;", (new_port, new_health, deployment_id))
                            elif new_port:
                                cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;", (new_port, deployment_id))
                            elif new_health:
                                cur.execute("UPDATE deployments SET health_check_path = %s WHERE deployment_id = %s;", (new_health, deployment_id))
                        conn.close()
                        logger.info(f"Updated deployment overrides from deployhub.yaml: port={new_port}, health_check_path={new_health}")
                    
                    runtime = config.get("runtime")
                    if runtime:
                        pack_args.extend(["--buildpack", runtime])
            except Exception as e:
                logger.warning(f"Failed to parse deployhub.yaml: {e}")

        # Task 16 / fix #4.4: Kaniko removed entirely.
        # Kaniko requires filesystem overlay capabilities that are incompatible
        # with runAsNonRoot: true + all capabilities dropped. It would silently
        # fail at snapshot creation inside the hardened builder pod.
        # Cloud Native Buildpacks (pack) is fully rootless and handles both
        # Dockerfile-based and non-Dockerfile repos natively via its detection
        # logic — no need to check for a Dockerfile ourselves.
        logger.info("Using Cloud Native Buildpacks (pack --publish).")
        cmd = [
            "pack", "build", image_name,
            "--path", workspace,
            "--builder", "paketobuildpacks/builder-jammy-base",
            "--publish",
        ] + pack_args

        logger.info(f"Executing: {' '.join(cmd)}")

        # Fix #5: The old code piped process.stdout directly into upload_fileobj.
        # upload_fileobj reads until EOF, which only arrives after the process
        # exits — but it held the pipe open and left no way to kill the process
        # on upload failure. The fix:
        #   1. Collect all stdout/stderr via communicate() with a timeout.
        #   2. Upload the collected bytes to S3.
        #   3. Check returncode AFTER communicate() returns.
        # This ensures the process is always reaped and the log is always uploaded.
        BUILD_TIMEOUT_SECONDS = int(os.getenv("BUILD_TIMEOUT_SECONDS", "600"))  # 10 min default
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        build_start = time.time()

        try:
            stdout_bytes, _ = process.communicate(timeout=BUILD_TIMEOUT_SECONDS)
            deployhub_build_duration_seconds.observe(time.time() - build_start)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_bytes, _ = process.communicate()
            deployhub_build_duration_seconds.observe(time.time() - build_start)
            logger.error(f"Build {deployment_id} timed out after {BUILD_TIMEOUT_SECONDS}s.")
            record_build(deployment_id, s3_log_key, "Failed")
            update_db_state(deployment_id, "Failed", "Build timed out.")
            return

        # Upload the collected log to S3
        try:
            s3.upload_fileobj(io.BytesIO(stdout_bytes), S3_LOG_BUCKET, s3_log_key)
        except Exception as e:
            logger.error(f"Failed to upload build log to S3 for {deployment_id}: {e}")
            # Non-fatal: the build result still matters more than the log upload

        if process.returncode == 0:
            logger.info(f"Build {deployment_id} successful. Checking ECR image scan results...")
            
            # ECR Image Scanning Gate
            try:
                ecr = boto3.client('ecr')
                # Use rsplit to safely handle any number of slashes in the registry hostname
                # e.g. "123456789012.dkr.ecr.us-east-1.amazonaws.com/deployhub-builds:abc123"
                registry_and_repo, image_tag = image_name.rsplit(':', 1)
                repo_name = registry_and_repo.split('/', 1)[1]  # strip the registry prefix
                
                scan_status = "IN_PROGRESS"
                attempts = 0
                while scan_status in ("IN_PROGRESS", "PENDING") and attempts < 12:
                    time.sleep(5)
                    attempts += 1
                    res = ecr.describe_image_scan_findings(
                        repositoryName=repo_name,
                        imageId={'imageTag': image_tag}
                    )
                    scan_status = res.get('imageScanStatus', {}).get('status', 'FAILED')
                    
                if scan_status == "COMPLETE":
                    findings = res.get('imageScanFindings', {}).get('findingSeverityCounts', {})
                    fail_on = os.getenv("IMAGE_SCAN_FAIL_ON", "CRITICAL")
                    
                    if findings.get(fail_on, 0) > 0:
                        logger.error(f"Image scan failed: {findings.get(fail_on)} {fail_on} vulnerabilities found.")
                        record_build(deployment_id, s3_log_key, "Failed")
                        update_db_state(deployment_id, "Failed", f"Image scan: {fail_on} vulnerability found")
                        return
                    else:
                        logger.info("Image scan passed.")
                else:
                    logger.warning(f"Image scan did not complete in time or failed. Status: {scan_status}")
            except Exception as e:
                logger.error(f"Error checking ECR image scan: {e}")
                
            record_build(deployment_id, s3_log_key, "Success")
            update_db_state(deployment_id, "Deploying")
        else:
            logger.error(f"Build {deployment_id} failed (exit code {process.returncode}).")
            record_build(deployment_id, s3_log_key, "Failed")
            update_db_state(deployment_id, "Failed", "Build step failed.")

    finally:
        # Fix #23: workspace cleanup is now guaranteed regardless of where
        # the function exits (git clone fail, timeout, S3 error, etc.)
        if os.path.exists(workspace):
            subprocess.run(["rm", "-rf", workspace])


def main():
    start_http_server(8001)
    logger.info(f"Builder {CONSUMER_NAME} started. Listening on {BUILDER_QUEUE}")
    while True:
        try:
            messages = r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {BUILDER_QUEUE: '>'}, count=1, block=5000
            )
            if messages:
                for stream, msg_list in messages:
                    for msg_id, data in msg_list:
                        deployment_id = data.get("deployment_id")
                        repo_url      = data.get("repo_url")
                        image_name    = data.get("image_name")

                        logger.info(f"Processing build task for deployment {deployment_id}")
                        try:
                            # Fix #3.2: validate before touching anything
                            validate_message(deployment_id, repo_url, image_name)
                            run_build(deployment_id, repo_url, image_name)
                            r.xack(BUILDER_QUEUE, CONSUMER_GROUP, msg_id)
                        except ValueError as e:
                            # Bad message — ACK it so it doesn't loop forever,
                            # and record the failure
                            logger.error(f"Invalid build message: {e}")
                            if deployment_id:
                                update_db_state(deployment_id, "Failed", str(e))
                            r.xack(BUILDER_QUEUE, CONSUMER_GROUP, msg_id)
                        except Exception as e:
                            # Fix #13: don't ACK on unexpected crash so the
                            # message stays pending and is re-claimed after
                            # PENDING_MESSAGE_TIMEOUT. Set state to Retry so
                            # the UI reflects the situation.
                            logger.error(f"Build task crashed for {deployment_id}: {e}")
                            if deployment_id:
                                update_db_state(deployment_id, "Retry", str(e))
                            # Intentionally not ACKing — lets KEDA keep the
                            # pending count elevated and triggers re-claim.
        except Exception as e:
            logger.error(f"Error reading from queue: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
