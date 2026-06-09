import os
import time
import logging
import yaml
import psycopg2
from psycopg2.extras import DictCursor
from jinja2 import Environment, FileSystemLoader
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from kubernetes.utils import create_from_yaml
from models import ProjectStatus, ProjectSchema
from metrics import (
    deployhub_drift_total, 
    deployhub_reconciliation_duration_seconds, 
    deployhub_deployment_success_total,
    start_metrics_server
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('controller')

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

k8s_client  = client.ApiClient()
k8s_core_api = client.CoreV1Api()
k8s_apps_api = client.AppsV1Api()
k8s_custom_api = client.CustomObjectsApi()

# Fix #20: raise if env var is missing rather than silently falling back to
# a hardcoded plaintext credential that will never work in-cluster.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

RECONCILIATION_INTERVAL = int(os.getenv("RECONCILIATION_INTERVAL", "60"))

# ECR registry hostname — used when rendering the tenant namespace template
# so each tenant namespace gets an ECR pull secret via ESO.
# Format: 123456789012.dkr.ecr.us-east-1.amazonaws.com
ECR_REGISTRY = os.getenv("ECR_REGISTRY", "")

jinja_env = Environment(loader=FileSystemLoader("templates"))


def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    # Fix #25: autocommit = False so PROVISIONING → READY transitions are
    # atomic. A crash after apply_manifests() but before the UPDATE will
    # roll back, leaving the project in PROVISIONING for the next loop.
    conn.autocommit = False
    return conn


def _wait_for_schema(max_attempts: int = 30, delay: int = 10):
    """
    Block until the schema bootstrap Job has run and the projects table exists.
    On a fresh cluster the Job runs as an ArgoCD PostSync hook — this can take
    30-60s after the controller pod starts. Without this guard the controller
    would crash-loop with 'relation "projects" does not exist'.
    """
    for attempt in range(1, max_attempts + 1):
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM projects LIMIT 1;")
            conn.close()
            logger.info("Database schema is ready.")
            return
        except psycopg2.OperationalError as e:
            logger.warning(f"DB not reachable yet (attempt {attempt}/{max_attempts}): {e}")
        except psycopg2.errors.UndefinedTable:
            logger.warning(f"Schema not ready yet (attempt {attempt}/{max_attempts}), waiting {delay}s...")
        except Exception as e:
            logger.warning(f"Unexpected DB error (attempt {attempt}/{max_attempts}): {e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(delay)
    raise RuntimeError(f"Database schema not ready after {max_attempts * delay}s — aborting")


def apply_manifests(manifest_str: str):
    """
    Fix #1: was writing to /tmp and calling a commented-out os.system().
    Now parses the multi-document YAML and applies each document via the
    kubernetes Python client — no shell, no kubectl binary required.
    """
    logger.info("Applying K8s manifests via Python client...")
    docs = list(yaml.safe_load_all(manifest_str))
    for doc in docs:
        if doc is None:
            continue
        try:
            create_from_yaml(k8s_client, yaml_objects=[doc], verbose=False)
            logger.info(f"Applied: {doc.get('kind', 'unknown')} / {doc.get('metadata', {}).get('name', 'unknown')}")
        except Exception as e:
            # Resource may already exist (idempotent re-apply). Log and continue.
            logger.warning(f"apply_manifests warning for {doc.get('kind')}: {e}")


def check_namespace_exists(namespace: str) -> bool:
    try:
        k8s_core_api.read_namespace(name=namespace)
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        raise


def delete_namespace(namespace: str):
    try:
        k8s_core_api.delete_namespace(name=namespace)
    except ApiException as e:
        if e.status != 404:
            raise


@deployhub_reconciliation_duration_seconds.time()
def reconcile():
    logger.info("Starting reconciliation loop...")
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM projects;")
            projects = cur.fetchall()

            for row in projects:
                project_data = dict(row)
                project_data["_id"] = project_data.pop("id")

                try:
                    project = ProjectSchema(**project_data)

                    with conn.cursor(cursor_factory=DictCursor) as project_cur:
                        if project.status == ProjectStatus.PROVISIONING:
                            logger.info(f"Provisioning project: {project.name} ({project.namespace})")
                            template = jinja_env.get_template("tenant.yaml.j2")
                            manifests = template.render(
                                namespace=project.namespace,
                                project_id=project.id,
                                ecr_registry=ECR_REGISTRY,
                            )
                            # Fix #1: actually applies manifests now.
                            apply_manifests(manifests)
    
                            # Fix #12: only mark READY after verifying the namespace
                            # was actually created. This breaks the race where the DB
                            # is marked READY before K8s has processed the request.
                            if check_namespace_exists(project.namespace):
                                project_cur.execute(
                                    "UPDATE projects SET status = %s WHERE id = %s;",
                                    (ProjectStatus.READY.value, project.id)
                                )
                                conn.commit()
                                logger.info(f"Project {project.name} provisioned and Ready.")
                            else:
                                # Namespace not visible yet; leave as PROVISIONING
                                # and retry on the next reconcile tick.
                                conn.rollback()
                                logger.info(f"Namespace {project.namespace} not yet visible; will retry.")
    
                        elif project.status == ProjectStatus.TERMINATING:
                            logger.info(f"Terminating project: {project.name} ({project.namespace})")
                            if check_namespace_exists(project.namespace):
                                delete_namespace(project.namespace)
                                logger.info(f"Namespace {project.namespace} deletion triggered.")
                                conn.commit()
                            else:
                                project_cur.execute("DELETE FROM projects WHERE id = %s;", (project.id,))
                                conn.commit()
                                logger.info(f"Project {project.name} permanently cleaned up.")
    
                        elif project.status == ProjectStatus.READY:
                            if not check_namespace_exists(project.namespace):
                                deployhub_drift_total.inc()
                                logger.warning(f"Drift detected! Namespace {project.namespace} missing for Ready project.")
                                project_cur.execute(
                                    "UPDATE projects SET status = %s WHERE id = %s;",
                                    (ProjectStatus.PROVISIONING.value, project.id)
                                )
                                conn.commit()
                            else:
                                reconcile_deployments(conn, project_cur, project)

                except Exception as e:
                    logger.error(f"Error reconciling project {row['id']}: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass

    finally:
        conn.close()


def reconcile_deployments(conn, cur, project):
    """Reconciles Deployments, Services, and HTTPRoutes for a ready project namespace."""
    cur.execute("SELECT * FROM deployments WHERE project_id = %s;", (project.id,))
    db_deployments = {row['deployment_id']: dict(row) for row in cur.fetchall()}

    try:
        k8s_deps = k8s_apps_api.list_namespaced_deployment(namespace=project.namespace)
        k8s_dep_names = {d.metadata.name: d for d in k8s_deps.items}

        # 1. Missing or Drifted Deployments
        for d_id, db_dep in db_deployments.items():
            if db_dep['state'] in ['Running', 'Verifying', 'Deploying']:
                if d_id not in k8s_dep_names:
                    deployhub_drift_total.inc()
                    logger.warning(f"Drift: Deployment {d_id} missing in K8s. Recreating...")
                    template = jinja_env.get_template("app-deployment.yaml.j2")
                    manifests = template.render(
                        deployment_name=d_id,
                        deployment_id=d_id,
                        namespace=project.namespace,
                        project_name=project.name,
                        image_uri=db_dep.get('image_uri', 'nginx:latest'),
                        port=db_dep.get('port', 8080),
                        replicas=db_dep.get('replicas', 1),
                        health_check_path=db_dep.get('health_check_path', '/')
                    )
                    apply_manifests(manifests)
                else:
                    k8s_dep = k8s_dep_names[d_id]
                    ready_replicas = k8s_dep.status.ready_replicas or 0
                    if ready_replicas == 0 and db_dep['state'] == 'Running':
                        deployhub_drift_total.inc()
                        logger.warning(f"Drift: Deployment {d_id} is failing in K8s.")
                        cur.execute(
                            "UPDATE deployments SET state = %s, last_error = %s WHERE deployment_id = %s;",
                            ('Failed', 'Kubernetes Deployment Failed/CrashLoopBackOff', d_id)
                        )
                        conn.commit()
                    elif ready_replicas > 0 and db_dep['state'] in ['Deploying', 'Verifying']:
                        logger.info(f"Deployment {d_id} is now Running (Ready Replicas: {ready_replicas})")
                        cur.execute(
                            "UPDATE deployments SET state = %s, last_error = NULL WHERE deployment_id = %s;",
                            ('Running', d_id)
                        )
                        conn.commit()
                        deployhub_deployment_success_total.inc()

        # 2. Orphan Resources Cleanup
        for k8s_name in k8s_dep_names.keys():
            if k8s_name not in db_deployments or db_deployments[k8s_name]['state'] not in ['Running', 'Verifying', 'Deploying']:
                deployhub_drift_total.inc()
                logger.warning(f"Drift: Orphan Deployment {k8s_name} found in K8s. Cleaning up...")
                k8s_apps_api.delete_namespaced_deployment(name=k8s_name, namespace=project.namespace)
                try:
                    k8s_core_api.delete_namespaced_service(name=f"{k8s_name}-svc", namespace=project.namespace)
                    k8s_custom_api.delete_namespaced_custom_object(
                        group="gateway.networking.k8s.io",
                        version="v1",
                        namespace=project.namespace,
                        plural="httproutes",
                        name=f"{k8s_name}-route"
                    )
                except ApiException:
                    pass

    except Exception as e:
        logger.error(f"Error reconciling deployments for {project.name}: {e}")


def main():
    # Fix #2: metrics on 9090, not 8080 (defined in metrics.py default)
    start_metrics_server(port=9090)
    _wait_for_schema()
    while True:
        reconcile()
        time.sleep(RECONCILIATION_INTERVAL)


if __name__ == "__main__":
    main()
