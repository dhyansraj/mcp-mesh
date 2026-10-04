# MCP Mesh Ingress Chart

Standalone Helm chart for managing ingress routing to MCP Mesh services with flexible DNS configuration.

## Overview

This chart provides ingress routing for MCP Mesh components with two routing patterns:

- **Host-based routing**: Each service gets its own subdomain (e.g., `registry.mcp-mesh.local`)
- **Path-based routing**: All services under one domain with path prefixes (e.g., `mcp-mesh.local/registry/`)

## Quick Start

### Prerequisites

- Kubernetes cluster with ingress controller (nginx, traefik, etc.)
- MCP Mesh core components deployed
- MCP Mesh agents deployed

An Ingress can only route to Services in its own namespace, so install this
chart into the namespace core and the agents run in. Backends are derived from
release names: the core components from `global.coreReleaseName` (default
`mcp-core`), each agent from its `name`.

### Installation

```bash
# Deploy with default configuration (host-based routing to the registry)
helm install mcp-ingress ./mcp-mesh-ingress -n mcp-mesh

# Deploy with custom domain
helm install mcp-ingress ./mcp-mesh-ingress -n mcp-mesh \
  --set global.domain=mycompany.local

# Deploy with path-based routing
helm install mcp-ingress ./mcp-mesh-ingress -n mcp-mesh \
  --set patterns.hostBased.enabled=false \
  --set patterns.pathBased.enabled=true
```

### Configuration Examples

#### Host-based Routing (Default)

```yaml
# values.yaml
patterns:
  hostBased:
    enabled: true

global:
  domain: "mcp-mesh.local"

agents:
  - name: hello-world
# Results in:
# registry.mcp-mesh.local → Registry service
# hello-world.mcp-mesh.local → Hello World agent
```

#### Path-based Routing

```yaml
# values.yaml
patterns:
  hostBased:
    enabled: false
  pathBased:
    enabled: true
    host: "mcp-mesh.local"

agents:
  - name: hello-world
# Results in:
# mcp-mesh.local/registry/ → Registry service
# mcp-mesh.local/hello-world/ → Hello World agent
```

#### Custom Agent Configuration

Only `name` is required. The rest default to what an agent installed as
`helm install <name> mcp-mesh-agent` creates; override them for anything else:

```yaml
# values.yaml
agents:
  - name: "my-custom-agent"
    host: "custom-agent" # default: the name
    service: "my-custom-agent-service" # default: <name>-mcp-mesh-agent
    port: 9000 # default: 8080
    path: "/custom-agent(/|$)(.*)" # default: /<name>(/|$)(.*)
    enabled: true # default: true
```

## Configuration

### Global Settings

| Parameter                | Description                                                     | Default          |
| ------------------------ | --------------------------------------------------------------- | ---------------- |
| `global.domain`          | Base domain for all services                                    | `mcp-mesh.local` |
| `global.ingressClass`    | Ingress controller class                                        | `nginx`          |
| `global.coreReleaseName` | Release name of the `mcp-mesh-core` install the core backends belong to | `mcp-core` |

### Routing Patterns

| Parameter                    | Description                      | Default          |
| ---------------------------- | -------------------------------- | ---------------- |
| `patterns.hostBased.enabled` | Enable host-based routing        | `true`           |
| `patterns.pathBased.enabled` | Enable path-based routing        | `false`          |
| `patterns.pathBased.host`    | Main host for path-based routing | `mcp-mesh.local` |

### Core Services

| Parameter               | Description                                                       | Default                                       |
| ----------------------- | ----------------------------------------------------------------- | --------------------------------------------- |
| `core.registry.enabled` | Include registry in ingress                                       | `true`                                        |
| `core.registry.service` | Registry Service name (rendered with `tpl` if it contains `{{ }}`) | `<global.coreReleaseName>-mcp-mesh-registry` |
| `core.ui.enabled`       | Include the dashboard UI in ingress                               | `false`                                       |
| `core.grafana.enabled`  | Include Grafana in ingress                                        | `false`                                       |
| `core.redis.enabled`    | Include Redis in ingress                                          | `false`                                       |

Each `core.<component>.service` defaults to
`<global.coreReleaseName>-mcp-mesh-<component>`.

### Agent Services

`agents` is empty by default. Add one entry per agent release to expose:

```yaml
agents:
  - name: "hello-world"
```

## Usage Patterns

### Pattern 1: Core + Agents + Ingress

```bash
# Deploy core infrastructure
helm install mcp-core ./mcp-mesh-core \
  -n mcp-mesh --create-namespace

# Deploy individual agents (each from its own image) into the same namespace
helm install hello-world ./mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/hello-world --set image.tag=v1.0.0
helm install system-agent ./mcp-mesh-agent -n mcp-mesh \
  --set image.repository=myregistry/system-agent --set image.tag=v1.0.0

# Deploy ingress routing, naming the agent releases to expose
helm install mcp-ingress ./mcp-mesh-ingress -n mcp-mesh \
  --set agents[0].name=hello-world \
  --set agents[1].name=system-agent
```

With core installed under another release name, add
`--set global.coreReleaseName=<release>`. If you install core and this chart
together as subcharts of your own umbrella chart, set `global.coreReleaseName`
to that umbrella's release name; the core chart accepts it when it matches its
own release.

### Pattern 2: Custom Service Names

```bash
# Deploy with custom service naming
helm install mcp-ingress ./mcp-mesh-ingress -n mcp-mesh \
  --set core.registry.service="my-registry-service" \
  --set agents[0].name=hello-world \
  --set agents[0].service="my-hello-world-service"
```

### Pattern 3: Production with TLS

```yaml
# values.yaml
tls:
  enabled: true
  certificates:
    - secretName: "mcp-mesh-tls"
      hosts:
        - "*.mcp-mesh.example.com"
        - "mcp-mesh.example.com"

global:
  domain: "mcp-mesh.example.com"
```

## Local Development

For local development with minikube:

```bash
# Get minikube IP
MINIKUBE_IP=$(minikube ip)

# Add hosts entries
echo "$MINIKUBE_IP registry.mcp-mesh.local" | sudo tee -a /etc/hosts
echo "$MINIKUBE_IP hello-world.mcp-mesh.local" | sudo tee -a /etc/hosts

# Test registry
curl http://registry.mcp-mesh.local/health
```

## Production Deployment

### AWS ALB Ingress Controller

```yaml
global:
  ingressClass: "alb"
  domain: "mcp-mesh.example.com"

patterns:
  hostBased:
    annotations:
      kubernetes.io/ingress.class: "alb"
      alb.ingress.kubernetes.io/scheme: "internet-facing"
```

### Nginx Ingress with TLS

```yaml
global:
  ingressClass: "nginx"

tls:
  enabled: true
  certificates:
    - secretName: "wildcard-tls"
      hosts: ["*.mcp-mesh.example.com"]

patterns:
  hostBased:
    annotations:
      cert-manager.io/cluster-issuer: "letsencrypt-prod"
```

## Troubleshooting

### Ingress Not Working

```bash
# Check ingress status
kubectl get ingress -n mcp-mesh

# Check ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller

# Verify service endpoints
kubectl get endpoints -n mcp-mesh
```

### DNS Resolution Issues

```bash
# Verify hosts file entries
cat /etc/hosts | grep mcp-mesh

# Test DNS resolution
nslookup registry.mcp-mesh.local

# Check ingress IP
kubectl get ingress -n mcp-mesh -o wide
```

## Values Reference

See [values.yaml](./values.yaml) for the complete list of configurable parameters.

## Contributing

This chart follows the same contribution guidelines as the main MCP Mesh project.
