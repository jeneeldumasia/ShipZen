import redis
import time
import logging
import json
import threading
import os
import subprocess
import tempfile
import shutil
import uuid
import boto3
import base64
import yaml
from kubernetes import client, config as k8s_config, watch
from kubernetes.client.rest import ApiException

from config import config
from queue_client import QueueClient
from state_machine import StateMachine, DeploymentState
from builder import DockerfileBuilder, RailpackBuilder, BuildpackBuilder
from metrics import (
    start_metrics_server, 
    shipzen_retry_total, 
    shipzen_queue_latency_seconds,
    shipzen_deployment_failure_total
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('worker')

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

batch_v1 = client.BatchV1Api()
core_v1 = client.CoreV1Api()
s3 = boto3.client('s3')

S3_LOG_BUCKET = os.environ.get("S3_LOG_BUCKET", "")


def get_db_conn():
    import psycopg2
    conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
    conn.autocommit = True
    return conn

def record_build(deployment_id: str, s3_key: str, status: str):
    build_id = str(uuid.uuid4())
    if not S3_LOG_BUCKET:
        logger.warning(f"S3_LOG_BUCKET not set — skipping build record for {deployment_id}")
        return
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

def monitor_job(job_name: str, deployment_id: str, image_name: str, state_machine: StateMachine):
    """Monitors the Kubernetes Job, streams logs to Redis, and finalizes the deployment."""
    logger.info(f"Monitoring Job {job_name} for deployment {deployment_id}")
    r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT)
    s3_log_key = f"logs/{deployment_id}/build.log"
    
    try:
        w = watch.Watch()
        pod_name = None
        
        # Wait for Pod to exist
        for event in w.stream(core_v1.list_namespaced_pod, namespace="shipzen-build", label_selector=f"job-name={job_name}", timeout_seconds=300):
            pod = event['object']
            status = pod.status.phase
            
            if status == "Pending":
                r.publish(f"shipzen:status:{deployment_id}", json.dumps({"state": "Queued", "last_error": None}))
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
                    r.publish(f"shipzen:logs:{deployment_id}", line.decode('utf-8', errors='replace'))
                except Exception:
                    pass
        except ApiException as e:
            logger.warning(f"Error reading pod logs: {e}")

        # Wait for Job to complete
        job_succeeded = False
        while True:
            job = batch_v1.read_namespaced_job(job_name, "shipzen-build")
            if job.status.succeeded and job.status.succeeded >= 1:
                job_succeeded = True
                break
            if job.status.failed and job.status.failed >= 1:
                break
            time.sleep(2)

        # Upload logs to S3
        stdout_bytes = b''.join(stdout_chunks)
        try:
            if S3_LOG_BUCKET:
                import io
                s3.upload_fileobj(io.BytesIO(stdout_bytes), S3_LOG_BUCKET, s3_log_key)
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")

        if job_succeeded:
            logger.info(f"Build {deployment_id} successful. Checking port/ECR...")
            
            # Dynamic Port Detection via Crane
            try:
                ecr = boto3.client('ecr', region_name=os.getenv("AWS_REGION", "us-east-1"))
                auth_data = ecr.get_authorization_token()['authorizationData'][0]
                token = base64.b64decode(auth_data['authorizationToken']).decode('utf-8')
                username, password = token.split(':')
                registry_url = auth_data['proxyEndpoint'].replace('https://', '')
                subprocess.run(["crane", "auth", "login", registry_url, "-u", username, "-p", password], check=True, capture_output=True)
                
                crane_out = subprocess.check_output(["crane", "config", image_name], text=True)
                config_json = json.loads(crane_out)
                exposed_ports = config_json.get("config", {}).get("ExposedPorts", {})
                
                if exposed_ports:
                    first_port = list(exposed_ports.keys())[0].split('/')[0]
                    conn = get_db_conn()
                    with conn.cursor() as cur:
                        cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;", (int(first_port), deployment_id))
                    conn.commit()
                    conn.close()
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
                    res = ecr.describe_image_scan_findings(repositoryName=repo_name, imageId={'imageTag': image_tag})
                    scan_status = res.get('imageScanStatus', {}).get('status', 'FAILED')
                    
                if scan_status == "COMPLETE":
                    findings = res.get('imageScanFindings', {}).get('findingSeverityCounts', {})
                    fail_on = os.getenv("IMAGE_SCAN_FAIL_ON", "CRITICAL")
                    if findings.get(fail_on, 0) > 0:
                        raise Exception(f"Image scan: {fail_on} vulnerability found")
            except Exception as e:
                logger.error(f"Image scan failed: {e}")
                record_build(deployment_id, s3_log_key, "Failed")
                state_machine.update_state(deployment_id, "Failed", str(e))
                return

            record_build(deployment_id, s3_log_key, "Success")
            state_machine.update_state(deployment_id, "Deploying")
            
        else:
            logger.error(f"Job {job_name} failed.")
            record_build(deployment_id, s3_log_key, "Failed")
            state_machine.update_state(deployment_id, "Failed", "Build step failed.")

    except Exception as e:
        logger.error(f"Error monitoring job {job_name}: {e}")
        record_build(deployment_id, s3_log_key, "Failed")
        state_machine.update_state(deployment_id, "Failed", str(e))
    finally:
        # Cleanup Job
        try:
            batch_v1.delete_namespaced_job(job_name, "shipzen-build", propagation_policy="Background")
        except Exception:
            pass


def process_message(queue: QueueClient, state_machine: StateMachine, message_id: str, data: dict):
    deployment_id = data.get("deployment_id")
    repo_url = data.get("repo_url")
    branch = data.get("branch", "main")
    image_name = data.get("image_name")
    
    if not deployment_id or not repo_url or not image_name:
        queue.add_to_dlq(message_id, data)
        return

    deployment = state_machine.get_deployment(deployment_id)
    if deployment and deployment.get("state") in [DeploymentState.BUILDING, DeploymentState.DEPLOYING, DeploymentState.RUNNING]:
        queue.ack_message(message_id)
        return

    logger.info(f"Processing deployment {deployment_id}")
    
    try:
        # Shallow clone to detect builder
        workspace = f"/tmp/workspace_{deployment_id}"
        os.makedirs(workspace, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--branch", branch, repo_url, workspace], check=True)
        
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
                        conn = get_db_conn()
                        with conn.cursor() as cur:
                            if new_port and new_health:
                                cur.execute("UPDATE deployments SET port = %s, health_check_path = %s WHERE deployment_id = %s;", (new_port, new_health, deployment_id))
                            elif new_port:
                                cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;", (new_port, deployment_id))
                            elif new_health:
                                cur.execute("UPDATE deployments SET health_check_path = %s WHERE deployment_id = %s;", (new_health, deployment_id))
                        conn.close()

        # SPA detection
        package_json_path = os.path.join(workspace, "package.json")
        if os.path.exists(package_json_path):
            with open(package_json_path, 'r') as f:
                pj = json.load(f)
            scripts = pj.get("scripts", {})
            deps = {**pj.get("dependencies", {}), **pj.get("devDependencies", {})}
            if "start" not in scripts:
                if any(m in deps for m in ["vite", "react-scripts", "vue", "svelte", "astro"]) or ("build" in scripts):
                    overrides["inject_server_js"] = True
            if "build" in scripts:
                overrides["bp_node_run_scripts"] = "build"

        # Builder detection
        builders = [DockerfileBuilder(), RailpackBuilder(), BuildpackBuilder()]
        selected_builder = None
        for b in builders:
            if b.detect(workspace):
                selected_builder = b
                break

        shutil.rmtree(workspace, ignore_errors=True)
        
        if not selected_builder:
            raise Exception("No suitable builder found")
            
        manifest = selected_builder.generate_job_manifest(deployment_id, repo_url, branch, image_name, overrides)
        job_name = manifest["metadata"]["name"]
        
        # Create Job
        batch_v1.create_namespaced_job(namespace="shipzen-build", body=manifest)
        logger.info(f"Created Job {job_name} for deployment {deployment_id}")
        
        # Spawn thread to monitor Job
        t = threading.Thread(target=monitor_job, args=(job_name, deployment_id, image_name, state_machine))
        t.start()
        
        queue.ack_message(message_id)

    except Exception as e:
        logger.error(f"Error processing {deployment_id}: {e}")
        state_machine.update_state(deployment_id, DeploymentState.RETRY, error_msg=str(e))
        queue.add_to_dlq(message_id, data)


def main():
    start_metrics_server(port=8000)
    queue = QueueClient()
    state_machine = StateMachine()

    logger.info(f"Worker {config.CONSUMER_NAME} started. Listening on stream {config.STREAM_NAME}")

    while True:
        try:
            claimed = queue.recover_pending_messages()
            if claimed:
                for msg_id, data in claimed:
                    process_message(queue, state_machine, msg_id, data)
                    
            messages = queue.get_messages(count=5, block_ms=2000)
            if messages:
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        process_message(queue, state_machine, msg_id, data)
        except Exception as e:
            logger.exception("Queue read error")
            time.sleep(2)


if __name__ == "__main__":
    main()
