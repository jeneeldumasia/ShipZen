# ShipZen

**ShipZen** is an enterprise-grade Internal Developer Platform (IDP) designed to orchestrate and automate Kubernetes deployments seamlessly. It provides a "Heroku-like" developer experience on top of raw Kubernetes primitives, utilizing Cloud Native Buildpacks, dynamic Gateway API routing, and state machine-driven asynchronous job execution.

## Executive Summary

ShipZen empowers development teams to deploy source code directly to a secure, isolated Kubernetes environment without writing `Dockerfiles` or YAML manifests. 

### Key Features
- **Zero-Config Deployments**: Automatic runtime detection and rootless container building via Cloud Native Buildpacks (CNB).
- **Asynchronous Orchestration**: Python-based Worker daemon leveraging Redis Streams for robust, fault-tolerant build pipelines.
- **Continuous Reconciliation**: A custom Python Controller continuously reconciles desired state stored in PostgreSQL against active Kubernetes resources.
- **Dynamic Routing**: Managed via Kubernetes Gateway API (Envoy Gateway), providing automatic TLS termination and strict host-based routing per deployment.
- **Deep Observability**: Out-of-the-box integration with the `kube-prometheus-stack` for Prometheus metrics, Grafana dashboards, and pod-level logs.
- **Multi-Tenant Isolation**: Each project executes within a strictly isolated Kubernetes namespace.

### Technology Stack
- **Frontend**: Next.js 14, Tailwind CSS, TypeScript
- **Backend / Workers**: Python, FastAPI, Psycopg2, Redis
- **Infrastructure**: Terraform, Amazon EKS (Kubernetes 1.36+), Karpenter (Auto-scaling)
- **Networking**: Envoy Gateway API, ExternalDNS, cert-manager
- **Observability**: Prometheus, Grafana, Node Exporter

---

## Architecture Overview

1. **API Server (`api/`)**: FastAPI REST interface handling authentication, webhooks, and state mutations.
2. **Worker (`worker/`)**: Background daemon consuming Redis streams. Handles repository cloning, Buildpack manifest generation, and Kubernetes Job orchestration.
3. **Controller (`controller/`)**: Reconciliation loop. Watches PostgreSQL for desired deployment states and translates them into raw Kubernetes Deployments, Services, and HTTPRoutes.
4. **Next.js UI (`ui/`)**: A sleek, modern dashboard providing a real-time view into the deployment state machine, build logs, and platform health.

---

## Local Development Setup

To run ShipZen locally or execute the test suite, ensure your machine meets the prerequisites.

### Prerequisites
- Python 3.14+
- Node.js 20+
- `pytest`, `flake8`
- (Optional) Docker for local Testcontainers execution

### 1. UI Development
The ShipZen frontend is a Next.js application located in `ui/`.
```bash
cd ui
npm install
npm run dev
```

### 2. Python Backend & Workers
The backend consists of the `api`, `worker`, and `controller` modules. 

#### Environment Setup
```bash
python -m venv venv
# Windows: venv\Scripts\activate | Mac/Linux: source venv/bin/activate
pip install -r api/requirements.txt
pip install -r worker/requirements.txt
pip install -r controller/requirements.txt
pip install -r tests/requirements.txt

# Required for local testing bypasses and admin bootstrapping
export ENABLE_LOCAL_STUB_AUTH=true
export ADMIN_EMAILS="admin@shipzen.local"
```

#### Running Tests
ShipZen uses `pytest` for unit and integration testing. The test suite is configured to gracefully skip tests requiring a live Docker daemon if one is not present.

```bash
pytest tests/
```

#### Linting and Code Quality
We enforce PEP8 standards and strict ESLint rules to maintain a production-ready codebase.
```bash
# Python
flake8 api/ worker/ controller/

# Next.js
npm run lint --prefix ui
```

---

## Infrastructure and Deployment

ShipZen's infrastructure is fully codified using Terraform, located in the `terraform/` directory.

### Quick Start (AWS EKS)
```bash
cd terraform
terraform init
terraform apply -var="aws_region=us-east-1"
```

*Note: Production deployments require configuring GitHub Actions OIDC federation and AWS IAM roles. See the `docs/` folder for comprehensive operational runbooks and Threat Models.*
