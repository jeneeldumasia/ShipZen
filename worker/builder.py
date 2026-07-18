from abc import ABC, abstractmethod
from typing import Dict, Any
import os
import json
import base64
import boto3
import logging
from kubernetes import client


def get_ecr_credentials():
    try:
        ecr = boto3.client('ecr', region_name='us-east-1')
        token_resp = ecr.get_authorization_token(
        )['authorizationData'][0]['authorizationToken']
        ecr_token = base64.b64decode(token_resp).decode('utf-8').split(':')[1]
        
        # Security Fix: Sync the ECR token to a K8s Secret so we don't have to pass it via CLI args
        try:
            core_v1 = client.CoreV1Api()
            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name="shipzen-ecr-secret", namespace="shipzen-build"),
                string_data={"ECR_TOKEN": ecr_token, "DOCKER_AUTH": token_resp}
            )
            try:
                core_v1.create_namespaced_secret(namespace="shipzen-build", body=secret)
            except client.ApiException as e:
                if e.status == 409:
                    core_v1.replace_namespaced_secret(name="shipzen-ecr-secret", namespace="shipzen-build", body=secret)
                else:
                    raise
        except Exception as k8s_e:
            logger.warning(f"Failed to sync ECR Secret to K8s: {k8s_e}")
            
        return token_resp, ecr_token
    except Exception as e:
        logger.warning(f"Warning: Failed to fetch ECR token: {e}")
        return "", ""


logger = logging.getLogger('builder')


class Builder(ABC):
    @abstractmethod
    def detect(self, workspace_path: str) -> bool:
        """Return True if this builder can handle the repository."""

    @abstractmethod
    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        """Generate the Kubernetes Job manifest dictionary."""


class DockerfileBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        return os.path.exists(os.path.join(workspace_path, "Dockerfile"))

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        token_resp, ecr_token = get_ecr_credentials()
        registry = image_uri.split('/')[0] if '/' in image_uri else ''

        # CRIT-01 Fix: Use environment variables instead of f-string interpolation
        # to prevent shell injection via malicious branch names or repo URLs.
        git_clone_env = [
            {"name": "GIT_REPO_URL", "value": repo_url},
            {"name": "GIT_BRANCH", "value": branch},
        ]
        if overrides.get("github_secret_name"):
            git_clone_env.append({"name": "GITHUB_TOKEN", "valueFrom": {"secretKeyRef": {"name": overrides["github_secret_name"], "key": "GITHUB_TOKEN"}}})
            clone_cmd = 'URL=$(echo "$GIT_REPO_URL" | sed "s|https://github.com/|https://x-access-token:${GITHUB_TOKEN}@github.com/|") && git clone --depth=1 --branch "$GIT_BRANCH" "$URL" /workspace'
        else:
            clone_cmd = 'git clone --depth=1 --branch "$GIT_BRANCH" "$GIT_REPO_URL" /workspace'

        build_script = (
            "set -e; "
            "mkdir -p ~/.config/buildkit; "
            "rootlesskit buildkitd --oci-worker-no-process-sandbox & "
            "BKPID=$!; "
            "for i in $(seq 1 30); do buildctl debug workers && break || sleep 1; done; "
            f"buildctl build "
            f"  --frontend dockerfile.v0 "
            f"  --local context=/workspace "
            f"  --local dockerfile=/workspace "
            f"  --output type=docker,dest=/shared/image.tar; "
            "EXIT=$?; kill $BKPID 2>/dev/null || true; exit $EXIT"
        )

        push_script = (
            "set -e; "
            f"crane auth login -u AWS -p $ECR_TOKEN {registry}; "
            f"crane push /shared/image.tar {image_uri}"
        )

        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": f"build-{deployment_id[:8]}",
                "namespace": "shipzen-build",
                "labels": {
                    "shipzen.jeneeldumasia.codes/deployment": deployment_id,
                    "shipzen.jeneeldumasia.codes/tier": "dockerfile"
                }
            },
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 1800,  # 30 mins
                "template": {
                    "metadata": {
                        "annotations": {
                            "container.apparmor.security.beta.kubernetes.io/buildkit": "unconfined"
                        }
                    },
                    "spec": {
                        "restartPolicy": "Never",
                        "tolerations": [
                            {"key": "shipzen.jeneeldumasia.codes/dedicated",
                                "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
                        ],
                        "initContainers": [
                            {
                                "name": "git-clone",
                                "image": "alpine/git:2.43.0",
                                "command": ["sh", "-c"],
                                "args": [clone_cmd],
                                "env": git_clone_env,
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            },
                            {
                                "name": "buildkit",
                                "image": "moby/buildkit:master-rootless",
                                "command": ["sh", "-c", build_script],
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "seccompProfile": {"type": "Unconfined"}
                                },
                                # No ECR token here!
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"},
                                    {"name": "shared", "mountPath": "/shared"}
                                ]
                            }
                        ],
                        "containers": [
                            {
                                "name": "push",
                                "image": "gcr.io/go-containerregistry/crane:debug",
                                "command": ["sh", "-c", push_script],
                                "envFrom": [{"secretRef": {"name": "shipzen-ecr-secret"}}],
                                "volumeMounts": [{"name": "shared", "mountPath": "/shared"}],
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {}},
                            {"name": "shared", "emptyDir": {}}
                        ]
                    }
                }
            }
        }


class RailpackBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        # Tier 3 fallback
        return os.path.exists(os.path.join(workspace_path, "Cargo.toml")) or os.path.exists(os.path.join(workspace_path, "bun.lockb"))

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        # For now, Railpack uses buildpacks as a placeholder until native compiler images are built
        token_resp, ecr_token = get_ecr_credentials()
        b = BuildpackBuilder()
        return b.generate_job_manifest(deployment_id, repo_url, branch, image_uri, overrides)


class BuildpackBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        return True  # Fallback for all other repos

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        token_resp, ecr_token = get_ecr_credentials()
        registry = image_uri.split('/')[0] if '/' in image_uri else ''

        # CRIT-01 Fix: Use environment variables instead of f-string interpolation
        git_clone_env = [
            {"name": "GIT_REPO_URL", "value": repo_url},
            {"name": "GIT_BRANCH", "value": branch},
        ]
        if overrides.get("github_secret_name"):
            git_clone_env.append({"name": "GITHUB_TOKEN", "valueFrom": {"secretKeyRef": {"name": overrides["github_secret_name"], "key": "GITHUB_TOKEN"}}})
            clone_cmd = 'URL=$(echo "$GIT_REPO_URL" | sed "s|https://github.com/|https://x-access-token:${GITHUB_TOKEN}@github.com/|") && git clone --depth=1 --branch "$GIT_BRANCH" "$URL" /workspace'
        else:
            clone_cmd = 'git clone --depth=1 --branch "$GIT_BRANCH" "$GIT_REPO_URL" /workspace'

        setup_script = f"""
{clone_cmd}
cd /workspace
"""
        if overrides.get("inject_server_js"):
            setup_script += """
cat << 'EOF' > server.cjs
const http = require('http');
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
EOF
# Inject start script
if [ -f package.json ]; then
  sed -i 's/"scripts": {/"scripts": { "start": "node server.cjs",/' package.json
fi
"""

        env_vars = []
        if overrides.get("bp_node_run_scripts"):
            env_vars.append({"name": "BP_NODE_RUN_SCRIPTS",
                            "value": overrides.get("bp_node_run_scripts")})

        pack_args = ["pack", "build", "local-image", "--path", "/workspace", "--builder",
                     "paketobuildpacks/builder-jammy-base", "--env", "NODE_OPTIONS=--max-old-space-size=2048"]
        if overrides.get("runtime"):
            pack_args.extend(["--buildpack", overrides.get("runtime")])

        push_script = (
            "set -e; "
            f"crane auth login -u AWS -p $ECR_TOKEN {registry}; "
            f"crane push /shared/image.tar {image_uri}"
        )

        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": f"build-{deployment_id[:8]}",
                "namespace": "shipzen-build",
                "labels": {
                    "shipzen.jeneeldumasia.codes/deployment": deployment_id,
                    "shipzen.jeneeldumasia.codes/tier": "buildpack"
                }
            },
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 1800,
                "ttlSecondsAfterFinished": 600,
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "tolerations": [
                            {"key": "shipzen.jeneeldumasia.codes/dedicated",
                                "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
                        ],
                        "initContainers": [
                            {
                                "name": "setup",
                                "image": "alpine/git:2.43.0",
                                "command": ["sh", "-c", setup_script],
                                "env": git_clone_env,
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            },
                            {
                                "name": "pack",
                                "image": "docker:24-dind-rootless",
                                "securityContext": {
                                    "privileged": False,
                                    "runAsUser": 1000,
                                    "seccompProfile": {"type": "Unconfined"}
                                },
                                "env": env_vars,
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"},
                                    {"name": "shared", "mountPath": "/shared"}
                                ],
                                "command": ["sh", "-c"],
                                "args": [
                                    "dockerd --tls=false & "
                                    "while ! docker info >/dev/null 2>&1; do sleep 1; done; "
                                    "wget -qO- https://github.com/buildpacks/pack/releases/download/v0.33.2/pack-v0.33.2-linux.tgz | tar -xz -C /usr/local/bin && "
                                    + " ".join(pack_args) + " && "
                                    "docker save local-image -o /shared/image.tar"
                                ]
                            }
                        ],
                        "containers": [
                            {
                                "name": "push",
                                "image": "gcr.io/go-containerregistry/crane:debug",
                                "command": ["sh", "-c", push_script],
                                "envFrom": [{"secretRef": {"name": "shipzen-ecr-secret"}}],
                                "volumeMounts": [{"name": "shared", "mountPath": "/shared"}],
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {}},
                            {"name": "shared", "emptyDir": {}}
                        ]
                    }
                }
            }
        }
