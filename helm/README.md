# MCP Mesh Helm Charts

Kubernetes deployment charts for MCP Mesh - a distributed agent orchestration framework.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      mcp-mesh-core                          │
│  ┌──────────┐ ┌───────┐ ┌──────────┐ ┌───────┐ ┌─────────┐  │
│  │ Registry │ │ Redis │ │ Postgres │ │ Tempo │ │ Grafana │  │
│  └──────────┘ └───────┘ └──────────┘ └───────┘ └─────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │  Agent   │    │  Agent   │    │  Agent   │
        │ (hello)  │    │ (system) │    │ (avatar) │
        └──────────┘    └──────────┘    └──────────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                    ┌─────────────────┐
                    │ mcp-mesh-ingress│
                    └─────────────────┘
```

## Quick Start

### Prerequisites

- Kubernetes 1.21+
- Helm 3.8+

### Installation

```bash
# 0. Only when installing from a clone of this repository: copy the Grafana
#    dashboards into the chart. They live in observability/ and are synced in
#    when the charts are released, so a released chart has them and a checkout
#    does not. Skip this and everything still installs and runs — Grafana just
#    comes up with its datasources and no MCP Mesh dashboards.
mkdir -p helm/mcp-mesh-grafana/files/dashboards
cp observability/grafana/dashboards/*.json helm/mcp-mesh-grafana/files/dashboards/

# 1. Install core infrastructure (registry + observability)
#    --create-namespace is what creates the namespace; the chart renders no
#    Namespace object of its own. See "Namespace handling" in
#    mcp-mesh-core/README.md — including the upgrade order for a release
#    installed with chart 3.4.x or earlier.
helm dependency update helm/mcp-mesh-core
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh --create-namespace

# 2. Install agents (repeat for each agent). Each agent ships as an image
#    with its code baked in — `meshctl scaffold` generates the Dockerfile and
#    a helm-values.yaml for it. See "Agent Images" below.
helm install hello-world helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/hello-world \
  --set image.tag=v1.0.0

# 3. (Optional) Install ingress for external access — in the same namespace,
#    naming each agent release to expose
helm install mcp-ingress helm/mcp-mesh-ingress -n mcp-mesh \
  --set agents[0].name=hello-world
```

## Charts

| Chart                                   | Description                                 | Documentation                          |
| --------------------------------------- | ------------------------------------------- | -------------------------------------- |
| [mcp-mesh-core](./mcp-mesh-core/)       | Registry, PostgreSQL, Redis, Grafana, Tempo | [README](./mcp-mesh-core/README.md)    |
| [mcp-mesh-agent](./mcp-mesh-agent/)     | Deploy MCP agents                           | [README](./mcp-mesh-agent/README.md)   |
| [mcp-mesh-ingress](./mcp-mesh-ingress/) | Ingress routing for services                | [README](./mcp-mesh-ingress/README.md) |

## Configuration

### Disable Optional Components

```bash
# Core without observability
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh --create-namespace \
  --set grafana.enabled=false \
  --set tempo.enabled=false
```

The registry always needs a database. Turning off the bundled PostgreSQL
(`postgres.enabled=false`) is for pointing it at an external one — see
"External managed datastores" in the
[mcp-mesh-core README](./mcp-mesh-core/README.md); the render fails if none is
configured.

### Agent Images

The agent chart runs an image with the agent's code in it, using the image's
own entrypoint. Build it from the Dockerfile `meshctl scaffold` generates (it
starts from `mcpmesh/python-runtime`, `mcpmesh/typescript-runtime` or
`mcpmesh/java-runtime`), then point the chart at it:

```bash
helm install my-agent helm/mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/my-agent \
  --set image.tag=v1.0.0
```

The agent's name comes from its code; `agent.name` overrides it. For a
single-file Python agent there is also a ConfigMap route on the stock runtime
image — see `agentCode` in the
[mcp-mesh-agent README](./mcp-mesh-agent/README.md#agent-code-configuration).

## Generated Credentials

Charts ship no default passwords. On install, the PostgreSQL password and the
Grafana admin password are auto-generated into Secrets (reused on upgrade):

```bash
# PostgreSQL (shared by provisioning, registry, and UI)
kubectl get secret mcp-core-mcp-mesh-postgres-credentials -n mcp-mesh \
  -o jsonpath='{.data.password}' | base64 -d

# Grafana admin
kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

Set explicit values (`global.postgres.password`,
`mcp-mesh-grafana.grafana.config.adminPassword`) or pre-created secrets
(`global.postgres.existingSecret`, `...grafana.config.existingSecret`) to
override — see the [mcp-mesh-core README](./mcp-mesh-core/README.md).

Generation reuses the existing value via `lookup`, which needs a live cluster.
Rendering without one (`helm template | kubectl apply`, Argo CD, Flux) emits a
new random password on every render — permanent drift on those Secrets. Use
pre-created secrets in such pipelines (`global.postgres.existingSecret`,
`mcp-mesh-grafana.grafana.config.existingSecret` — add
`...config.generatedSecret: false` to make a missing reference fail the render
instead of regenerating). Switching an already-installed release over to a
pre-created secret is a two-step change for Grafana — follow the procedure in
the [mcp-mesh-core README](./mcp-mesh-core/README.md#adopting-existingsecret-on-an-existing-install).

## Verify Installation

```bash
# Check all pods are running
kubectl get pods -n mcp-mesh

# Test registry health
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000 &
curl http://localhost:8000/health

# List registered agents
curl http://localhost:8000/agents
```

## Uninstall

```bash
helm uninstall mcp-ingress -n mcp-mesh
helm uninstall hello-world -n mcp-mesh
helm uninstall mcp-core -n mcp-mesh
kubectl delete namespace mcp-mesh
```

## Service Discovery

Agents auto-register with the registry using these default endpoints:

| Service  | Internal URL                      |
| -------- | --------------------------------- |
| Registry | `mcp-core-mcp-mesh-registry:8000` |
| Redis    | `mcp-core-mcp-mesh-redis:6379`    |
| Tempo    | `mcp-core-mcp-mesh-tempo:4317`    |
| Grafana  | `mcp-core-mcp-mesh-grafana:3000`  |
