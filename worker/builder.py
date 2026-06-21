import os
import yaml
import json
import logging
import subprocess
import tempfile
import shutil
from abc import ABC, abstractmethod
from typing import Dict, Any

logger = logging.getLogger('builder')

class Builder(ABC):
    @abstractmethod
    def detect(self, workspace_path: str) -> bool:
        """Return True if this builder can handle the repository."""
        pass

    @abstractmethod
    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        """Generate the Kubernetes Job manifest dictionary."""
        pass


class DockerfileBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        return os.path.exists(os.path.join(workspace_path, "Dockerfile"))

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
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
                "activeDeadlineSeconds": 900,  # 15 mins
                "template": {
                    "metadata": {
                        "annotations": {
                            "container.apparmor.security.beta.kubernetes.io/buildkit": "unconfined"
                        }
                    },
                    "spec": {
                        "restartPolicy": "Never",

                        "tolerations": [
                            {"key": "shipzen.jeneeldumasia.codes/dedicated", "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
                        ],
                        "initContainers": [
                            {
                                "name": "git-clone",
                                "image": "alpine/git:2.43.0",
                                "command": ["sh", "-c"],
                                "args": [f"git clone --depth=1 --branch {branch} {repo_url} /workspace"],
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            }
                        ],
                        "containers": [
                            {
                                "name": "buildkit",
                                "image": "moby/buildkit:master-rootless",
                                "command": ["rootlesskit", "buildkitd"],
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "seccompProfile": {"type": "Unconfined"}
                                },
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                # Instead of daemonizing and running buildctl in the same container, we can just run the daemon in the background and then run buildctl
                                "lifecycle": {
                                    "postStart": {
                                        "exec": {
                                            "command": ["sh", "-c", f"while ! buildctl debug workers; do sleep 1; done; buildctl build --frontend dockerfile.v0 --local context=/workspace --local dockerfile=/workspace --output type=image,name={image_uri},push=true && kill 1"]
                                        }
                                    }
                                }
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {}}
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
        b = BuildpackBuilder()
        return b.generate_job_manifest(deployment_id, repo_url, branch, image_uri, overrides)


class BuildpackBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        return True  # Fallback for all other repos

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        
        # Build the script for initContainer that clones and applies the SPA hack if needed
        # Overrides contains instructions if we need to inject server.js
        setup_script = f"""
git clone --depth=1 --branch {branch} {repo_url} /workspace
cd /workspace
"""
        if overrides.get("inject_server_js"):
            setup_script += """
cat << 'EOF' > server.js
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
  sed -i 's/"scripts": {/"scripts": { "start": "node server.js",/' package.json
fi
"""

        env_vars = []
        if overrides.get("bp_node_run_scripts"):
            env_vars.append({"name": "BP_NODE_RUN_SCRIPTS", "value": overrides.get("bp_node_run_scripts")})
            
        pack_args = ["pack", "build", image_uri, "--path", "/workspace", "--builder", "paketobuildpacks/builder-jammy-base", "--publish"]
        if overrides.get("runtime"):
            pack_args.extend(["--buildpack", overrides.get("runtime")])

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
                "activeDeadlineSeconds": 900,
                "template": {
                    "spec": {
                        "restartPolicy": "Never",

                        "tolerations": [
                            {"key": "shipzen.jeneeldumasia.codes/dedicated", "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
                        ],
                        "initContainers": [
                            {
                                "name": "setup",
                                "image": "alpine/git:2.43.0",
                                "command": ["sh", "-c", setup_script],
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            }
                        ],
                        "containers": [
                            {
                                "name": "pack",
                                "image": "buildpacksio/pack:0.33.2",
                                "command": pack_args,
                                "env": env_vars,
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {}}
                        ]
                    }
                }
            }
        }
