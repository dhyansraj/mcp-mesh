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

### Installation

```bash
# Deploy with default configuration (host-based routing)
helm install mcp-ingress ./mcp-mesh-ingress

# Deploy with custom domain
helm install mcp-ingress ./mcp-mesh-ingress \
  --set global.domain=mycompany.local

# Deploy with path-based routing
helm install mcp-ingress ./mcp-mesh-ingress \
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
# Results in:
# mcp-mesh.local/registry/ → Registry service
# mcp-mesh.local/hello-world/ → Hello World agent
```

#### Custom Agent Configuration

```yaml
# values.yaml
agents:
  - name: "my-custom-agent"
    enabled: true
    host: "custom-agent"
    service: "my-custom-agent-service"
    port: 9000
    path: "/custom-agent(/|$)(.*)"
```

## Configuration

### Global Settings

| Parameter                 | Description                           | Default                |
| ------------------------- | ------------------------------------- | ---------------------- |
| `global.domain`           | Base domain for all services          | `mcp-mesh.local`       |
| `global.ingressClass`     | Ingress controller class              | `nginx`                |
| `global.serviceNamespace` | Namespace where services are deployed | `""` (same as release) |

### Routing Patterns

| Parameter                    | Description                      | Default          |
| ---------------------------- | -------------------------------- | ---------------- |
| `patterns.hostBased.enabled` | Enable host-based routing        | `true`           |
| `patterns.pathBased.enabled` | Enable path-based routing        | `false`          |
| `patterns.pathBased.host`    | Main host for path-based routing | `mcp-mesh.local` |

### Core Services

| Parameter               | Description                 | Default                                 |
| ----------------------- | --------------------------- | --------------------------------------- |
| `core.registry.enabled` | Include registry in ingress | `true`                                  |
| `core.registry.service` | Registry service name       | `{{ .Release.Name }}-mcp-mesh-registry` |
| `core.redis.enabled`    | Include Redis in ingress    | `false`                                 |

### Agent Services

Configure the `agents` array to include your deployed agents:

```yaml
agents:
  - name: "hello-world"
    enabled: true
    host: "hello-world"
    service: "hello-world-mcp-mesh-agent"
    port: 9090
```

## Usage Patterns

### Pattern 1: Core + Agents + Ingress

```bash
# Deploy core infrastructure
helm install mcp-core ./mcp-mesh-core

# Deploy individual agents
helm install hello-world ./mcp-mesh-agent --set agent.name=hello-world
helm install system-agent ./mcp-mesh-agent --set agent.name=system-agent

# Deploy ingress routing
helm install mcp-ingress ./mcp-mesh-ingress
```

### Pattern 2: Custom Service Names

```bash
# Deploy with custom service naming
helm install mcp-ingress ./mcp-mesh-ingress \
  --set core.registry.service="my-registry-service" \
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
