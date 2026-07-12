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
import boto3
import redis
import json
from models import ProjectStatus, ProjectSchema
from metrics import (
    shipzen_drift_total,
    shipzen_reconciliation_duration_seconds,
    shipzen_deployment_success_total,
    shipzen_active_deployments,
    start_metrics_server
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('controller')

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

k8s_client = client.ApiClient()
k8s_core_api = client.CoreV1Api()
k8s_apps_api = client.AppsV1Api()
k8s_custom_api = client.CustomObjectsApi()

# Fix #20: raise if env var is missing rather than silently falling back to
# a hardcoded plaintext credential that will never work in-cluster.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

RECONCILIATION_INTERVAL = int(os.getenv("RECONCILIATION_INTERVAL", "15"))

# ECR registry hostname — used when rendering the tenant namespace template
# so each tenant namespace gets an ECR pull secret via ESO.
# Format: 123456789012.dkr.ecr.us-east-1.amazonaws.com
ECR_REGISTRY = os.getenv("ECR_REGISTRY", "")

REDIS_HOST = os.getenv("REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Module-level Redis singleton — created once, reused across all reconcile ticks.
_redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

jinja_env = Environment(loader=FileSystemLoader("templates"))


def ensure_ecr_repository(project_id: str):
    try:
        ecr = boto3.client('ecr', region_name=os.getenv(
            "AWS_REGION", "us-east-1"))
        repo_name = f"shipzen-builds/{project_id}"
        try:
            ecr.describe_repositories(repositoryNames=[repo_name])
        except ecr.exceptions.RepositoryNotFoundException:
            logger.info(f"Creating ECR repository {repo_name}")
            ecr.create_repository(
                repositoryName=repo_name,
                imageScanningConfiguration={'scanOnPush': True},
                imageTagMutability='IMMUTABLE'
            )
    except Exception as e:
        logger.error(f"Failed to ensure ECR repository exists: {e}")

def delete_ecr_repository(project_id: str):
    try:
        ecr = boto3.client('ecr', region_name=os.getenv("AWS_REGION", "us-east-1"))
        repo_name = f"shipzen-builds/{project_id}"
        logger.info(f"Deleting ECR repository {repo_name}")
        ecr.delete_repository(repositoryName=repo_name, force=True)
    except ecr.exceptions.RepositoryNotFoundException:
        pass
    except Exception as e:
        logger.error(f"Failed to delete ECR repository: {e}")


from psycopg2.pool import ThreadedConnectionPool
db_pool = None

def get_db_connection():
    global db_pool
    if db_pool is None:
        db_pool = ThreadedConnectionPool(1, 20, DATABASE_URL)
    conn = db_pool.getconn()
    conn.autocommit = False
    return conn

def close_db_connection(conn):
    if db_pool:
        db_pool.putconn(conn)
    else:
        conn.close()


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
            logger.info("Database schema is ready.")
            return
        except psycopg2.OperationalError as e:
            logger.warning(
                f"DB not reachable yet (attempt {attempt}/{max_attempts}): {e}")
        except psycopg2.errors.UndefinedTable:
            logger.warning(
                f"Schema not ready yet (attempt {attempt}/{max_attempts}), waiting {delay}s...")
        except Exception as e:
            logger.warning(
                f"Unexpected DB error (attempt {attempt}/{max_attempts}): {e}")
        finally:
            if conn is not None:
                try:
                    close_db_connection(conn)
                except Exception:
                    pass
        time.sleep(delay)
    raise RuntimeError(
        f"Database schema not ready after {max_attempts * delay}s — aborting")


def apply_manifests(manifest_str: str):
    """
    Parses the multi-document YAML and applies each document via the
    kubernetes Python client. If the resource already exists, it is patched.
    """
    logger.info("Applying K8s manifests via Python client...")
    docs = list(yaml.safe_load_all(manifest_str))
    for doc in docs:
        if doc is None:
            continue

        kind = doc.get("kind")
        name = doc.get("metadata", {}).get("name")
        namespace = doc.get("metadata", {}).get("namespace", "default")

        try:
            if kind == "HTTPRoute":
                k8s_custom_api.create_namespaced_custom_object(
                    "gateway.networking.k8s.io", "v1", namespace, "httproutes", doc)
                logger.info(f"Applied: {kind} / {name}")
                continue
            elif kind == "ExternalSecret":
                k8s_custom_api.create_namespaced_custom_object(
                    "external-secrets.io", "v1beta1", namespace, "externalsecrets", doc)
                logger.info(f"Applied: {kind} / {name}")
                continue

            create_from_yaml(k8s_client, yaml_objects=[doc], verbose=False)
            logger.info(f"Applied: {kind} / {name}")
        except ApiException as e:
            if e.status == 409:
                try:
                    if kind == "Deployment":
                        k8s_apps_api.patch_namespaced_deployment(
                            name, namespace, doc)
                    elif kind == "Service":
                        k8s_core_api.patch_namespaced_service(
                            name, namespace, doc)
                    elif kind == "HTTPRoute":
                        k8s_custom_api.patch_namespaced_custom_object(
                            "gateway.networking.k8s.io", "v1", namespace, "httproutes", name, doc)
                    elif kind == "ExternalSecret":
                        k8s_custom_api.patch_namespaced_custom_object(
                            "external-secrets.io", "v1beta1", namespace, "externalsecrets", name, doc)
                    elif kind == "PodDisruptionBudget":
                        client.PolicyV1Api().patch_namespaced_pod_disruption_budget(name, namespace, doc)
                    elif kind == "NetworkPolicy":
                        client.NetworkingV1Api().patch_namespaced_network_policy(name, namespace, doc)
                    elif kind == "ResourceQuota":
                        k8s_core_api.patch_namespaced_resource_quota(
                            name, namespace, doc)
                    elif kind == "LimitRange":
                        k8s_core_api.patch_namespaced_limit_range(
                            name, namespace, doc)
                    elif kind == "Role":
                        client.RbacAuthorizationV1Api().patch_namespaced_role(name, namespace, doc)
                    elif kind == "RoleBinding":
                        client.RbacAuthorizationV1Api().patch_namespaced_role_binding(name, namespace, doc)
                    else:
                        logger.warning(f"Patching not implemented for {kind}")
                        continue
                    logger.info(f"Patched: {kind} / {name}")
                except Exception as patch_e:
                    logger.error(f"Failed to patch {kind} {name}: {patch_e}")
            else:
                logger.warning(f"apply_manifests API error for {kind}: {e}")
        except Exception as e:
            logger.warning(f"apply_manifests error for {kind}: {e}")


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


@shipzen_reconciliation_duration_seconds.time()
def reconcile():
    logger.info("Starting reconciliation loop...")
    # Outer connection: read-only project list fetch only.
    # Each project then gets its own connection so a failure in one project
    # cannot roll back or corrupt the state of another.
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM projects;")
            projects = [dict(row) for row in cur.fetchall()]
    finally:
        close_db_connection(conn)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_reconcile_project, dict(row)) for row in projects]
        concurrent.futures.wait(futures)


def _reconcile_project(project_data: dict):
    project_data["_id"] = project_data.pop("id")

    # Per-project connection — failure here cannot affect other projects
    project_conn = get_db_connection()
    try:
        project = ProjectSchema(**project_data)

        with project_conn.cursor(cursor_factory=DictCursor) as project_cur:
            if project.status == ProjectStatus.PROVISIONING:
                logger.info(
                    f"Provisioning project: {project.name} ({project.namespace})")
                template = jinja_env.get_template("tenant.yaml.j2")
                manifests = template.render(
                    namespace=project.namespace,
                    project_id=project.id,
                    ecr_registry=ECR_REGISTRY,
                )
                apply_manifests(manifests)

                if check_namespace_exists(project.namespace):
                    ensure_ecr_repository(project.id)
                    project_cur.execute(
                        "UPDATE projects SET status = %s WHERE id = %s;",
                        (ProjectStatus.READY.value, project.id)
                    )
                    project_conn.commit()
                    logger.info(
                        f"Project {project.name} provisioned and Ready.")
                else:
                    project_conn.rollback()
                    logger.info(
                        f"Namespace {project.namespace} not yet visible; will retry.")

            elif project.status == ProjectStatus.TERMINATING:
                logger.info(
                    f"Terminating project: {project.name} ({project.namespace})")
                if check_namespace_exists(project.namespace):
                    delete_namespace(project.namespace)
                    logger.info(
                        f"Namespace {project.namespace} deletion triggered.")
                    project_conn.commit()
                else:
                    delete_ecr_repository(project.id)
                    project_cur.execute(
                        "DELETE FROM projects WHERE id = %s;", (project.id,))
                    project_conn.commit()
                    logger.info(
                        f"Project {project.name} permanently cleaned up.")

            elif project.status == ProjectStatus.READY:
                if not check_namespace_exists(project.namespace):
                    shipzen_drift_total.inc()
                    logger.warning(
                        f"Drift detected! Namespace {project.namespace} missing for Ready project.")
                    project_cur.execute(
                        "UPDATE projects SET status = %s WHERE id = %s;",
                        (ProjectStatus.PROVISIONING.value, project.id)
                    )
                    project_conn.commit()
                else:
                    reconcile_deployments(
                        project_conn, project_cur, project)

    except Exception as e:
        logger.error(f"Error reconciling project {row['id']}: {e}")
        try:
            project_conn.rollback()
        except Exception:
            pass
        try:
            err_conn = get_db_connection()
            try:
                with err_conn.cursor() as err_cur:
                    err_cur.execute(
                        "UPDATE projects SET status = %s WHERE id = %s;",
                        (ProjectStatus.FAILED.value, project_data['_id'])
                    )
                err_conn.commit()
            finally:
                close_db_connection(err_conn)
        except Exception as rb_err:
            logger.error(f"Failed to set FAILED state: {rb_err}")
    finally:
        close_db_connection(project_conn)


def reconcile_deployments(conn, cur, project):
    """Reconciles Deployments, Services, and HTTPRoutes for a ready project namespace."""
    cur.execute("SELECT * FROM deployments WHERE project_id = %s;",
                (project.id,))
    db_deployments = {str(row['deployment_id']): dict(row)
                      for row in cur.fetchall()}

    try:
        k8s_deps = k8s_apps_api.list_namespaced_deployment(
            namespace=project.namespace)
        k8s_dep_names = {d.metadata.name: d for d in k8s_deps.items}

        k8s_svcs = k8s_core_api.list_namespaced_service(
            namespace=project.namespace)
        k8s_svc_names = {s.metadata.name for s in k8s_svcs.items}

        try:
            k8s_routes = k8s_custom_api.list_namespaced_custom_object(
                "gateway.networking.k8s.io", "v1", namespace=project.namespace, plural="httproutes"
            )
            k8s_route_names = {r['metadata']['name']
                               for r in k8s_routes.get('items', [])}
        except ApiException:
            k8s_route_names = set()

        # 1. Missing or Drifted Deployments
        for d_id, db_dep in db_deployments.items():
            if db_dep['state'] in ['Running', 'Verifying', 'Deploying']:
                missing_resources = (
                    d_id not in k8s_dep_names or
                    f"{d_id}-svc" not in k8s_svc_names or
                    f"{d_id}-route" not in k8s_route_names
                )
                if missing_resources:
                    shipzen_drift_total.inc()
                    logger.warning(
                        f"Drift: Deployment {d_id} or its resources missing in K8s. Recreating...")
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
                        shipzen_drift_total.inc()
                        logger.warning(
                            f"Drift: Deployment {d_id} is failing in K8s.")
                        cur.execute(
                            "UPDATE deployments SET state = %s, last_error = %s WHERE deployment_id = %s;",
                            ('Failed', 'Kubernetes Deployment Failed/CrashLoopBackOff', d_id)
                        )
                        conn.commit()
                        try:
                            _redis_client.publish(f"shipzen:status:{d_id}", json.dumps(
                                {"state": "Failed", "last_error": "Kubernetes Deployment Failed/CrashLoopBackOff"}))
                        except Exception as pub_e:
                            logger.warning(
                                f"Failed to publish to Redis: {pub_e}")
                    elif ready_replicas > 0 and db_dep['state'] in ['Deploying', 'Verifying']:
                        logger.info(
                            f"Deployment {d_id} is now Running (Ready Replicas: {ready_replicas})")
                        cur.execute(
                            "UPDATE deployments SET state = %s, last_error = NULL WHERE deployment_id = %s;",
                            ('Running', d_id)
                        )
                        conn.commit()
                        shipzen_deployment_success_total.inc()
                        try:
                            _redis_client.publish(f"shipzen:status:{d_id}", json.dumps(
                                {"state": "Running", "last_error": None}))
                        except Exception as pub_e:
                            logger.warning(
                                f"Failed to publish to Redis: {pub_e}")

        # 2. Orphan Resources Cleanup
        # States that indicate a live or in-flight deployment — never garbage collect these.
        _LIVE_STATES = {'Running', 'Verifying', 'Deploying', 'Queued', 'Building', 'Failed', 'DLQ'}
        for k8s_name in k8s_dep_names.keys():
            if k8s_name not in db_deployments or db_deployments[k8s_name]['state'] not in _LIVE_STATES:
                shipzen_drift_total.inc()
                logger.warning(
                    f"Drift: Orphan Deployment {k8s_name} found in K8s. Cleaning up...")
                k8s_apps_api.delete_namespaced_deployment(
                    name=k8s_name, namespace=project.namespace)
                try:
                    k8s_core_api.delete_namespaced_service(
                        name=f"{k8s_name}-svc", namespace=project.namespace)
                    k8s_custom_api.delete_namespaced_custom_object(
                        group="gateway.networking.k8s.io",
                        version="v1",
                        namespace=project.namespace,
                        plural="httproutes",
                        name=f"{k8s_name}-route"
                    )
                except ApiException:
                    pass

        # 3. Update active_deployments metric
        running_count = sum(
            1 for d_id, db_dep in db_deployments.items()
            if db_dep['state'] == 'Running' and d_id in k8s_dep_names and (k8s_dep_names[d_id].status.ready_replicas or 0) > 0
        )
        shipzen_active_deployments.labels(
            namespace=project.namespace).set(running_count)

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
