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
import json
import base64
from prometheus_client import Histogram, start_http_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('builder')

shipzen_build_duration_seconds = Histogram(
    'shipzen_build_duration_seconds',
    'Build duration from clone to push',
    buckets=[30, 60, 120, 300, 600, 900]
)

REDIS_HOST    = os.getenv("REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
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
            if error_msg:
                cur.execute(
                    "UPDATE deployments SET state = %s, last_error = %s, updated_at = NOW() WHERE deployment_id = %s;",
                    (state, error_msg, deployment_id)
                )
            else:
                cur.execute(
                    "UPDATE deployments SET state = %s, updated_at = NOW() WHERE deployment_id = %s;",
                    (state, deployment_id)
                )
        conn.commit()
        conn.close()
        
        # Publish state update to Redis for real-time WebSocket listeners
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
            payload = json.dumps({"state": state, "last_error": error_msg})
            r.publish(f"shipzen:status:{deployment_id}", payload)
        except Exception as e:
            logger.warning(f"Failed to publish status to Redis: {e}")
            
    except Exception as e:
        logger.error(f"Failed to update deployment state {state} for {deployment_id}: {e}")


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


def run_build(deployment_id: str, repo_url: str, branch: str, image_name: str):
    workspace = f"/workspace/{deployment_id}"
    os.makedirs(workspace, exist_ok=True)

    try:
        # Fix #3.1: git clone failure now records a failed build entry so
        # post-mortem debugging is possible even when the build never started.
        logger.info(f"Cloning {repo_url} (branch: {branch}) into {workspace}")
        try:
            subprocess.run(["git", "clone", "--depth=1", "--branch", branch, repo_url, workspace], check=True)
        except subprocess.CalledProcessError as e:
            record_build(deployment_id, f"logs/{deployment_id}/build.log", "Failed")
            update_db_state(deployment_id, "Failed", f"git clone failed: {e}")
            return

        s3_log_key = f"logs/{deployment_id}/build.log"

        # Check for shipzen.yaml overrides
        config_path = os.path.join(workspace, "shipzen.yaml")
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
                        logger.info(f"Updated deployment overrides from shipzen.yaml: port={new_port}, health_check_path={new_health}")
                    
                    runtime = config.get("runtime")
                    if runtime:
                        pack_args.extend(["--buildpack", runtime])
            except Exception as e:
                logger.warning(f"Failed to parse shipzen.yaml: {e}")

        # === START AUTO-DETECT FOR FRONTEND SPAS ===
        # Cloud Native Buildpacks (Paketo) requires a start script for Node.js apps.
        # Vite/React SPAs often don't have one. We dynamically inject a pure-Node static server.
        package_json_path = os.path.join(workspace, "package.json")
        if os.path.exists(package_json_path):
            try:
                with open(package_json_path, 'r') as f:
                    pj = json.load(f)
                scripts = pj.get("scripts", {})
                deps = pj.get("dependencies", {})
                dev_deps = pj.get("devDependencies", {})
                all_deps = {**deps, **dev_deps}
                
                frontend_markers = ["vite", "react-scripts", "vue", "astro", "gatsby", "svelte"]
                
                if "start" not in scripts:
                    if "next" in all_deps:
                        logger.info("Detected Next.js without start script. Injecting next start.")
                        pj.setdefault("scripts", {})["start"] = "next start"
                        with open(package_json_path, "w") as f:
                            json.dump(pj, f, indent=2)
                        if "build" in scripts:
                            pack_args.extend(["--env", "BP_NODE_RUN_SCRIPTS=build"])
                            
                    elif any(m in all_deps for m in frontend_markers) or ("build" in scripts and "vite" in all_deps):
                        logger.info("Detected static SPA without start script. Auto-configuring server.js...")
                        
                        if "build" in scripts:
                            pack_args.extend(["--env", "BP_NODE_RUN_SCRIPTS=build"])
                            
                        server_js_path = os.path.join(workspace, "server.js")
                        if not os.path.exists(server_js_path):
                            with open(server_js_path, "w") as f:
                                f.write("""const http = require('http');
const fs = require('fs');
const path = require('path');
const PORT = process.env.PORT || 8080;
const dirs = ['dist', 'build', 'out', 'public', '.'];
let DIR = __dirname;
for (const d of dirs) {
    if (fs.existsSync(path.join(__dirname, d, 'index.html'))) {
        DIR = path.join(__dirname, d);
        break;
    }
}
const mimeTypes = {
    '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
    '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpg',
    '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff': 'application/font-woff',
    '.woff2': 'application/font-woff2', '.ttf': 'application/font-ttf'
};
const server = http.createServer((req, res) => {
    let reqUrl = req.url.split('?')[0];
    let filePath = path.join(DIR, reqUrl === '/' ? 'index.html' : reqUrl);
    let extname = path.extname(filePath);
    if (!extname) {
        filePath = path.join(DIR, 'index.html');
        extname = '.html';
    }
    fs.readFile(filePath, (err, content) => {
        if (err) {
            if (err.code === 'ENOENT') {
                fs.readFile(path.join(DIR, 'index.html'), (err2, content2) => {
                    if (err2) { res.writeHead(500); res.end('Error'); }
                    else { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(content2, 'utf-8'); }
                });
            } else {
                res.writeHead(500); res.end(`Server Error: ${err.code}`);
            }
        } else {
            res.writeHead(200, { 'Content-Type': mimeTypes[extname] || 'application/octet-stream' });
            res.end(content, 'utf-8');
        }
    });
});
server.listen(PORT, () => console.log(`Static server listening on port ${PORT} serving ${DIR}`));
""")
                            pj.setdefault("scripts", {})["start"] = "node server.js"
                            with open(package_json_path, "w") as f:
                                json.dump(pj, f, indent=2)
            except Exception as e:
                logger.warning(f"Error during static site auto-detection: {e}")
        # === END AUTO-DETECT ===

        # Task 16 / fix #4.4: Kaniko removed entirely.
        # Kaniko requires filesystem overlay capabilities that are incompatible
        # with runAsNonRoot: true + all capabilities dropped. It would silently
        # fail at snapshot creation inside the hardened builder pod.
        # Cloud Native Buildpacks (pack) is fully rootless and handles both
        # Dockerfile-based and non-Dockerfile repos natively via its detection
        # logic — no need to check for a Dockerfile ourselves.
        # Ensure ECR repository exists
        # ECR repo creation is now handled by the Controller during project provisioning

        logger.info("Using Cloud Native Buildpacks (pack --publish).")
        cmd = [
            "pack", "build", image_name,
            "--path", workspace,
            "--builder", "paketobuildpacks/builder-jammy-base",
            "--publish",
        ] + pack_args

        logger.info(f"Executing: {' '.join(cmd)}")

        # Fix #5: Avoid pipe deadlocks by reading line by line.
        # This also allows us to stream logs in real-time via Redis Pub/Sub (SSE Feature)
        BUILD_TIMEOUT_SECONDS = int(os.getenv("BUILD_TIMEOUT_SECONDS", "600"))  # 10 min default
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        build_start = time.time()

        stdout_chunks = []
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        try:
            for line in iter(process.stdout.readline, b''):
                stdout_chunks.append(line)
                try:
                    r.publish(f"shipzen:logs:{deployment_id}", line.decode('utf-8', errors='replace'))
                except Exception:
                    pass
            process.stdout.close()
            process.wait(timeout=max(1, BUILD_TIMEOUT_SECONDS - (time.time() - build_start)))
            stdout_bytes = b''.join(stdout_chunks)
            shipzen_build_duration_seconds.observe(time.time() - build_start)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            stdout_bytes = b''.join(stdout_chunks)
            shipzen_build_duration_seconds.observe(time.time() - build_start)
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
            
            # Dynamic Port Detection using crane
            try:
                ecr = boto3.client('ecr')
                auth_data = ecr.get_authorization_token()['authorizationData'][0]
                token = base64.b64decode(auth_data['authorizationToken']).decode('utf-8')
                username, password = token.split(':')
                registry_url = auth_data['proxyEndpoint'].replace('https://', '')
                subprocess.run(["crane", "auth", "login", registry_url, "-u", username, "-p", password], check=True, capture_output=True)
                
                crane_out = subprocess.check_output(["crane", "config", image_name], text=True)
                config_json = json.loads(crane_out)
                exposed_ports = config_json.get("config", {}).get("ExposedPorts", {})
                
                if exposed_ports:
                    # '8080/tcp' -> '8080'
                    first_port = list(exposed_ports.keys())[0].split('/')[0]
                    conn = get_db_conn()
                    with conn.cursor() as cur:
                        cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;", (int(first_port), deployment_id))
                    conn.commit()
                    conn.close()
                    logger.info(f"Dynamically discovered and assigned port {first_port} from image {image_name}")
            except Exception as e:
                logger.warning(f"Failed to extract exposed port using crane: {e}")
            
            # ECR Image Scanning Gate
            try:
                ecr = boto3.client('ecr')
                # Use rsplit to safely handle any number of slashes in the registry hostname
                # e.g. "123456789012.dkr.ecr.us-east-1.amazonaws.com/shipzen-builds:abc123"
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


def recover_pending_messages():
    """Pending Message Recovery via XPENDING + XCLAIM."""
    timeout_ms = (int(os.getenv("BUILD_TIMEOUT_SECONDS", "600")) + 60) * 1000
    try:
        pending = r.xpending_range(BUILDER_QUEUE, CONSUMER_GROUP, '-', '+', 100)
        for msg in pending:
            message_id = msg['message_id']
            consumer = msg['consumer']
            idle_time = msg['time_since_delivered']

            if idle_time > timeout_ms:
                logger.info(f"Recovering pending message {message_id} from {consumer}")
                r.xclaim(
                    BUILDER_QUEUE, CONSUMER_GROUP, CONSUMER_NAME,
                    timeout_ms, [message_id]
                )
    except Exception as e:
        logger.error(f"Error recovering pending messages: {e}")

def main():
    start_http_server(8001)
    logger.info(f"Builder {CONSUMER_NAME} started. Listening on {BUILDER_QUEUE}")
    while True:
        try:
            recover_pending_messages()
            messages = r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {BUILDER_QUEUE: '>'}, count=1, block=5000
            )
            if messages:
                for stream, msg_list in messages:
                    for msg_id, data in msg_list:
                        deployment_id = data.get("deployment_id")
                        repo_url      = data.get("repo_url")
                        branch        = data.get("branch", "main")
                        image_name    = data.get("image_name")

                        logger.info(f"Processing build task for deployment {deployment_id}")
                        try:
                            # Fix #3.2: validate before touching anything
                            validate_message(deployment_id, repo_url, image_name)
                            run_build(deployment_id, repo_url, branch, image_name)
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
