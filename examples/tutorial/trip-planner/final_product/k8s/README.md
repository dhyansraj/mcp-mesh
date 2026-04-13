# TripPlanner Kubernetes Deployment

Production-grade Kubernetes deployment of TripPlanner with SPIRE workload identity and mTLS between all mesh agents.

## Architecture

```
                    Ingress (optional TLS termination)
                           |
                         nginx
                    (OpenResty + Lua)
                    /       |       \
               /auth/*   /api/*     /*
            Google OAuth   |      React SPA
                           |
                    gateway agent
                    (FastAPI bridge)
                           |
            +--------------+--------------+
            |              |              |
      planner-agent  budget-analyst  logistics-planner
            |              |              |
     +------+------+      |              |
     |      |      |      |              |
  flight  hotel  weather poi  user-prefs chat-history
  agent   agent  agent  agent  agent     agent
     |
  claude-provider / openai-provider

  --- All inter-agent communication secured by SPIRE mTLS ---

  SPIRE Server (StatefulSet)  <-->  SPIRE Agent (DaemonSet)
       |                                  |
   Trust domain:                  Workload API socket:
   mcp-mesh.local                 /run/spire/agent/sockets/agent.sock
```

## Prerequisites

- Kubernetes cluster (minikube, EKS, GKE, AKS)
- kubectl configured for the cluster
- Helm 3.8+ (OCI registry support)
- Docker registry accessible from the cluster
- API keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- Google OAuth credentials (or use `DEV_MODE=true`)

## Build and Push Agent Images

Each agent needs a Docker image built and pushed to your registry. From the `final_product/` directory:

```bash
REGISTRY="your-registry.example.com/trip-planner"

# Build all agent images
for agent in flight-agent hotel-agent weather-agent poi-agent \
             user-prefs-agent chat-history-agent claude-provider \
             openai-provider planner-agent gateway budget-analyst \
             adventure-advisor logistics-planner; do
  docker build -t $REGISTRY/$agent:latest ./$agent
  docker push $REGISTRY/$agent:latest
done

# Build nginx image (includes Lua scripts and UI assets)
cd web && npm install && npm run build && cd ..
docker build -t $REGISTRY/nginx:latest \
  --build-arg NGINX_CONF=nginx.conf \
  -f nginx/Dockerfile nginx/
# Copy built UI into the image or mount as volume
docker push $REGISTRY/nginx:latest
```

If using minikube, build images directly in the minikube Docker daemon:

```bash
eval $(minikube docker-env)
# Then run the docker build commands above (skip push)
```

Update the `image.repository` in each `helm/values-*.yaml` to match your registry.

## Deploy

### Quick start

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
./install.sh
```

### Custom namespace

```bash
./install.sh staging
```

### Preview (dry run)

```bash
./install.sh trip-planner --dry-run
```

### What install.sh does

1. Creates the namespace
2. Creates LLM API key secrets
3. Deploys SPIRE server (StatefulSet) and agent (DaemonSet)
4. Waits for SPIRE server readiness
5. Registers workload entries (mesh-registry, mesh-agent)
6. Installs mcp-mesh-core (registry, PostgreSQL, Redis, Tempo, Grafana)
7. Installs all 13 mesh agents with SPIRE mTLS enabled
8. Deploys nginx (OpenResty) with OAuth configuration

## Verify

```bash
# Check all pods are running
kubectl -n trip-planner get pods

# Check SPIRE health
kubectl -n trip-planner exec -it statefulset/spire-server -- \
  /opt/spire/bin/spire-server healthcheck

# Check registered entries
kubectl -n trip-planner exec -it statefulset/spire-server -- \
  /opt/spire/bin/spire-server entry show

# Port-forward registry and list agents
kubectl -n trip-planner port-forward svc/mcp-core-mcp-mesh-registry 8000:8000 &
meshctl list
```

## Access the UI

```bash
kubectl -n trip-planner port-forward svc/nginx 80:80
open http://localhost
```

Or configure the Ingress resource in `nginx/ingress.yaml` for external access.

## Security Overview

### SPIRE Trust Domain

- **Trust domain**: `mcp-mesh.local`
- **Server**: StatefulSet with SQLite persistence, port 8081
- **Agent**: DaemonSet on every node, exposes Workload API socket
- **Node attestation**: Kubernetes Projected Service Account Token (k8s_psat)
- **Workload attestation**: Kubernetes pod labels (k8s)

### Workload Identities

| Workload | SPIFFE ID | Selector |
|----------|-----------|----------|
| Registry | `spiffe://mcp-mesh.local/mesh-registry` | `k8s:pod-label:app.kubernetes.io/name:mcp-mesh-registry` |
| All agents | `spiffe://mcp-mesh.local/mesh-agent` | `k8s:pod-label:app.kubernetes.io/name:mcp-mesh-agent` |

### mTLS Flow

1. SPIRE agent runs on each node, exposing `/run/spire/agent/sockets/agent.sock`
2. Each mesh agent pod mounts the socket via hostPath volume
3. On startup, agents fetch X.509-SVIDs from the SPIRE Workload API
4. All agent-to-agent and agent-to-registry communication uses mTLS
5. Certificate rotation is automatic (SVID TTL: 1h, CA TTL: 24h)

### Certificate Lifecycle

- **CA TTL**: 24 hours (SPIRE server rotates automatically)
- **SVID TTL**: 1 hour (agents re-fetch before expiry)
- **No manual cert management**: SPIRE handles issuance and rotation

## Teardown

```bash
./teardown.sh              # Default namespace
./teardown.sh staging      # Custom namespace
```

This removes nginx, all agents, core infrastructure, SPIRE, secrets, RBAC, and the namespace.

## Customization

### Google OAuth

Edit `nginx/secret.yaml` with your credentials, or create the secret imperatively:

```bash
kubectl -n trip-planner create secret generic nginx-oauth \
  --from-literal=GOOGLE_CLIENT_ID=your-id.apps.googleusercontent.com \
  --from-literal=GOOGLE_CLIENT_SECRET=your-secret \
  --from-literal=DEV_MODE=false
```

For local development without OAuth, set `DEV_MODE=true`.

### Resource Limits

Edit the `resources` section in each `helm/values-*.yaml` file. LLM agents (planner-agent, budget-analyst, adventure-advisor, logistics-planner) request more memory by default.

### External Ingress

Uncomment and configure `nginx/ingress.yaml` for your ingress controller and TLS provider.
