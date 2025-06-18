# MCP Mesh Kubernetes Deployment Guide

This guide covers deploying MCP Mesh to Kubernetes, testing functionality, and validating resilience.

## Prerequisites

- Kubernetes cluster (minikube, kind, or production cluster)
- `kubectl` configured
- Docker images built and available in cluster

## Quick Start

### 1. Deploy Base Infrastructure

```bash
# Deploy everything (namespace, postgres, registry, and agents)
kubectl apply -k base/
```

### 2. Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n mcp-mesh

# Expected output:
# mcp-mesh-hello-world-xxx    1/1     Running
# mcp-mesh-postgres-0         1/1     Running
# mcp-mesh-registry-0         1/1     Running
# mcp-mesh-system-agent-xxx   1/1     Running
```

### 3. Setup Port Forwarding

```bash
# Registry API (for meshctl)
kubectl port-forward -n mcp-mesh svc/mcp-mesh-registry 8000:8000 &

# Hello World Agent HTTP API
kubectl port-forward -n mcp-mesh svc/hello-world-agent 8081:8080 &

# System Agent HTTP API
kubectl port-forward -n mcp-mesh svc/system-agent 8082:8080 &
```

## Testing and Validation

### 1. List Registered Agents

```bash
# Build meshctl if not already built
make build

# List all registered agents
./bin/meshctl list agents

# Expected output showing both agents with their capabilities
```

### 2. Test MCP Function Calls

```bash
# Test hello world function (should get date from system agent)
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Expected response with current date from system agent
```

### 3. Test Direct System Agent

```bash
# Test system agent date service directly
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "get_current_time", "arguments": {}}}' | jq .
```

### 4. Test Advanced Functions

```bash
# Test advanced greeting with system info
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_typed", "arguments": {}}}' | jq .

# Test dependency test function (multiple dependencies)
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "test_dependencies", "arguments": {}}}' | jq .
```

## Resilience Testing

### 1. Test System Agent Failure

```bash
# Scale down system agent to simulate failure
kubectl scale deployment system-agent -n mcp-mesh --replicas=0

# Verify agent is gone
kubectl get pods -n mcp-mesh | grep system-agent

# Test hello world function - should gracefully degrade
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Expected: "Hello from MCP Mesh! (Date service not available yet)"
```

### 2. Test System Agent Recovery

```bash
# Scale system agent back up
kubectl scale deployment system-agent -n mcp-mesh --replicas=1

# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l app=system-agent -n mcp-mesh --timeout=60s

# Test hello world function - should work again with date
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Expected: "Hello from MCP Mesh! Today is [current date]"
```

### 3. Test Registry Resilience

```bash
# Restart registry pod
kubectl delete pod -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry

# Wait for registry to come back
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mcp-mesh-registry -n mcp-mesh --timeout=120s

# Agents should automatically reconnect - test functionality
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

### 4. Test Multi-Replica Scaling

```bash
# Scale hello-world agent to multiple replicas
kubectl scale deployment hello-world-agent -n mcp-mesh --replicas=3

# Verify all replicas are running
kubectl get pods -n mcp-mesh | grep hello-world

# All replicas should register and be available for load balancing
./bin/meshctl list agents
```

## Kubernetes Files Reference

### Core Infrastructure (`base/`)

#### **Namespace & RBAC**

- `namespace.yaml` - Creates `mcp-mesh` namespace
- `registry/rbac.yaml` - Role-based access control for registry
- `registry/serviceaccount.yaml` - Service account for registry pods

#### **PostgreSQL Database**

- `postgres/postgres-statefulset.yaml` - PostgreSQL database with persistent storage
- `postgres/postgres-service.yaml` - Database service for registry connectivity

#### **Registry**

- `registry/statefulset.yaml` - MCP Mesh registry with leader election
- `registry/service.yaml` - Registry service for agent connections
- `registry/service-headless.yaml` - Headless service for StatefulSet
- `registry/configmap.yaml` - Registry configuration
- `registry/secret.yaml` - Database credentials and auth tokens
- `registry/backup-cronjob.yaml` - Automated database backups

#### **Agent Infrastructure**

- `agents/agent-code-configmap.yaml` - Agent Python code with K8s keep-alive loops
- `agents/configmap.yaml` - Base agent configuration
- `agents/secret.yaml` - Agent credentials and API keys
- `agents/hello-world-deployment.yaml` - Hello World agent deployment
- `agents/system-agent-deployment.yaml` - System agent deployment

#### **Storage**

- `registry/pvc.yaml` - Persistent volume claims for registry data

### Custom Resources (`base/crds/`)

- `mcpagent-crd.yaml` - Custom Resource Definition for declarative agent management

## Health Checks and Monitoring

### Health Endpoints

All components expose health endpoints:

```bash
# Registry health
curl http://localhost:8000/health

# Agent health
curl http://localhost:8081/health
curl http://localhost:8082/health
```

### Log Monitoring

```bash
# Registry logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry -f

# Agent logs
kubectl logs -n mcp-mesh -l app=hello-world-agent -f
kubectl logs -n mcp-mesh -l app=system-agent -f

# Database logs
kubectl logs -n mcp-mesh mcp-mesh-postgres-0 -f
```

## Cleanup

```bash
# Delete all MCP Mesh resources
kubectl delete namespace mcp-mesh

# Stop port forwards
pkill -f "kubectl port-forward"
```

## Troubleshooting

### Common Issues

1. **Pods stuck in `Completed` state**

   - The base ConfigMap includes keep-alive loops for K8s compatibility
   - Restart agent pods: `kubectl delete pod -n mcp-mesh -l app.kubernetes.io/component=agent`

2. **Registry connection failures**

   - Verify PostgreSQL is running: `kubectl get pods -n mcp-mesh | grep postgres`
   - Check registry logs: `kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry`

3. **Dependency injection not working**

   - Verify both agents are registered: `./bin/meshctl list agents`
   - Check registry connectivity from agents
   - Ensure agents have network access to registry service

4. **Image pull errors**
   - For minikube: Use `eval $(minikube docker-env)` before building images
   - Ensure `imagePullPolicy: Never` for local images

### Useful Commands

```bash
# Quick status check
kubectl get all -n mcp-mesh

# Describe failing pod
kubectl describe pod <pod-name> -n mcp-mesh

# Access pod shell for debugging
kubectl exec -it <pod-name> -n mcp-mesh -- /bin/sh

# Port forward for debugging
kubectl port-forward -n mcp-mesh <pod-name> <local-port>:<container-port>
```

This deployment provides a production-ready MCP Mesh setup with proper resilience, monitoring, and testing capabilities.
