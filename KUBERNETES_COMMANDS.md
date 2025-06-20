# MCP Mesh Kubernetes Commands Reference

This file contains all the essential kubectl commands used for building, deploying, testing, and managing MCP Mesh in Kubernetes.

## 🏗️ Build Commands

### Switch to Minikube Docker Environment

```bash
# CRITICAL: Always run this before building images for minikube
eval $(minikube docker-env)
```

### Build Docker Images

```bash
# Build registry image (no cache to ensure fresh dependencies)
eval $(minikube docker-env) && docker build --no-cache -t mcp-mesh-registry -f docker/registry/Dockerfile .

# Build base agent image (no cache to ensure fresh dependencies)
eval $(minikube docker-env) && docker build --no-cache -t mcp-mesh-base -f docker/agent/Dockerfile.base .

# Check built images
eval $(minikube docker-env) && docker images | grep mcp-mesh
```

## 🚀 Deploy Commands

### Deploy MCP Mesh

```bash
# Deploy all resources
minikube kubectl -- apply -k examples/k8s/base/

# Alternative: Use regular kubectl if available
kubectl apply -k examples/k8s/base/
```

### Delete and Redeploy (Clean Slate)

```bash
# Delete everything
minikube kubectl -- delete -k examples/k8s/base/

# Redeploy everything
minikube kubectl -- apply -k examples/k8s/base/
```

### Restart Specific Deployments

```bash
# Restart agent deployments after config changes
minikube kubectl -- rollout restart -n mcp-mesh deployment/mcp-mesh-hello-world deployment/mcp-mesh-system-agent

# Restart specific deployment
minikube kubectl -- rollout restart -n mcp-mesh deployment/mcp-mesh-hello-world
```

## 📊 Status Check Commands

### Check Pod Status

```bash
# Check all pods in mcp-mesh namespace
minikube kubectl -- get pods -n mcp-mesh

# Check all resources
minikube kubectl -- get all -n mcp-mesh

# Watch pods in real-time
minikube kubectl -- get pods -n mcp-mesh -w
```

### Check Deployment Status

```bash
# Check deployment rollout status
minikube kubectl -- rollout status -n mcp-mesh deployment/mcp-mesh-hello-world
minikube kubectl -- rollout status -n mcp-mesh deployment/mcp-mesh-system-agent
```

### Describe Resources (Debugging)

```bash
# Describe failing pod
minikube kubectl -- describe pod <pod-name> -n mcp-mesh

# Describe deployment
minikube kubectl -- describe deployment mcp-mesh-hello-world -n mcp-mesh
```

## 🔌 Port Forward Commands

### Setup Port Forwarding

```bash
# Kill existing port forwards
pkill -f "kubectl port-forward" || true

# Registry API (for meshctl)
minikube kubectl -- port-forward -n mcp-mesh svc/mcp-mesh-registry 8000:8000 > /dev/null 2>&1 &

# Hello World Agent HTTP API
minikube kubectl -- port-forward -n mcp-mesh svc/mcp-mesh-hello-world 8081:8080 > /dev/null 2>&1 &

# System Agent HTTP API
minikube kubectl -- port-forward -n mcp-mesh svc/mcp-mesh-system-agent 8082:8080 > /dev/null 2>&1 &
```

### Background Port Forward (Alternative)

```bash
# Start port forward in background
nohup minikube kubectl -- port-forward -n mcp-mesh svc/mcp-mesh-hello-world 8081:8080 > /dev/null 2>&1 &
```

## 📝 Log Commands

### View Agent Logs

```bash
# View hello-world agent logs (latest 20 lines)
minikube kubectl -- logs -n mcp-mesh deployment/mcp-mesh-hello-world --tail=20

# View system agent logs
minikube kubectl -- logs -n mcp-mesh deployment/mcp-mesh-system-agent --tail=20

# Follow logs in real-time
minikube kubectl -- logs -n mcp-mesh deployment/mcp-mesh-hello-world -f

# View logs from specific pod
minikube kubectl -- logs -n mcp-mesh pod/<pod-name>
```

### View Registry Logs

```bash
# View registry logs
minikube kubectl -- logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry --tail=20

# Follow registry logs
minikube kubectl -- logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry -f
```

### View Database Logs

```bash
# View PostgreSQL logs
minikube kubectl -- logs -n mcp-mesh mcp-mesh-postgres-0 --tail=20
```

## ⚡ Scale Commands

### Scale Agents Up/Down

```bash
# Scale system agent to 0 (simulate failure)
minikube kubectl -- scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=0

# Scale system agent back up
minikube kubectl -- scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=1

# Scale hello-world to multiple replicas
minikube kubectl -- scale deployment hello-world-agent -n mcp-mesh --replicas=3

# Wait for pod to be ready after scaling up
minikube kubectl -- wait --for=condition=ready pod -l app=system-agent -n mcp-mesh --timeout=60s
```

## 🧪 MCP Test Commands

### Health Checks

```bash
# Check agent health endpoints
curl http://localhost:8081/health
curl http://localhost:8082/health

# Check registry health
curl http://localhost:8000/health
```

### List Tools

```bash
# List tools on hello-world agent
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/list", "params": {}}' | jq .

# List tools on system agent
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/list", "params": {}}' | jq .
```

### Test Function Calls

```bash
# Test hello world function (should get date from system agent)
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Test system agent date service directly
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "get_current_time", "arguments": {}}}' | jq .

# Test advanced greeting with system info
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_typed", "arguments": {}}}' | jq .

# Test dependency test function (multiple dependencies)
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "test_dependencies", "arguments": {}}}' | jq .
```

## 🔧 Configuration Commands

### Enable Debug Mode

```bash
# Edit configmap to enable debug logging
# Change MCP_MESH_LOG_LEVEL=INFO to MCP_MESH_LOG_LEVEL=DEBUG
# Change MCP_MESH_DEBUG_MODE=false to MCP_MESH_DEBUG_MODE=true

# Apply changes and restart agents
minikube kubectl -- apply -k examples/k8s/base/
minikube kubectl -- rollout restart -n mcp-mesh deployment/mcp-mesh-hello-world deployment/mcp-mesh-system-agent
```

### Update Agent Code

```bash
# After modifying agent code in configmap
minikube kubectl -- apply -k examples/k8s/base/
minikube kubectl -- rollout restart -n mcp-mesh deployment/mcp-mesh-hello-world
```

## 🧹 Cleanup Commands

### Delete Everything

```bash
# Delete all MCP Mesh resources
minikube kubectl -- delete namespace mcp-mesh

# Alternative: Delete using kustomize
minikube kubectl -- delete -k examples/k8s/base/

# Stop all port forwards
pkill -f "kubectl port-forward"
```

### Restart Specific Components

```bash
# Restart registry pod
minikube kubectl -- delete pod -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry

# Restart all agent pods
minikube kubectl -- delete pod -n mcp-mesh -l app.kubernetes.io/component=agent
```

## 🔍 Debugging Commands

### Access Pod Shell

```bash
# Access hello-world agent shell
minikube kubectl -- exec -it -n mcp-mesh deployment/mcp-mesh-hello-world -- /bin/sh

# Access registry shell
minikube kubectl -- exec -it -n mcp-mesh mcp-mesh-registry-0 -- /bin/sh
```

### Check Resource Usage

```bash
# Check resource usage
minikube kubectl -- top pods -n mcp-mesh

# Check node resources
minikube kubectl -- top nodes
```

### Network Testing

```bash
# Test connectivity from one pod to another
minikube kubectl -- exec -it -n mcp-mesh deployment/mcp-mesh-hello-world -- ping mcp-mesh-registry

# Check service endpoints
minikube kubectl -- get endpoints -n mcp-mesh
```

## 🎯 Complete Workflow Commands

### Full Deployment Workflow

```bash
# 1. Switch to minikube docker
eval $(minikube docker-env)

# 2. Build images
docker build --no-cache -t mcp-mesh-registry -f docker/registry/Dockerfile .
docker build --no-cache -t mcp-mesh-base -f docker/agent/Dockerfile.base .

# 3. Deploy
minikube kubectl -- apply -k examples/k8s/base/

# 4. Wait for pods
minikube kubectl -- wait --for=condition=ready pod -l app.kubernetes.io/component=agent -n mcp-mesh --timeout=120s

# 5. Setup port forwarding
minikube kubectl -- port-forward -n mcp-mesh svc/mcp-mesh-registry 8000:8000 &
minikube kubectl -- port-forward -n mcp-mesh svc/mcp-mesh-hello-world 8081:8080 &

# 6. Test functionality
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

### Resilience Testing Workflow

```bash
# 1. Test normal operation
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# 2. Scale down system agent (simulate failure)
minikube kubectl -- scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=0

# 3. Test degraded operation
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# 4. Scale system agent back up
minikube kubectl -- scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=1

# 5. Wait for recovery
minikube kubectl -- wait --for=condition=ready pod -l app.kubernetes.io/name=mcp-mesh-system-agent -n mcp-mesh --timeout=60s

# 6. Test recovery
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

## 🗄️ PostgreSQL Database Commands

### Access PostgreSQL

```bash
# Access PostgreSQL shell
minikube kubectl -- exec -it -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh

# Run single command
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "SELECT version();"
```

### View Database Schema

```bash
# List all tables
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "\dt"

# Describe specific table
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "\d agents"

# Show table contents
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "SELECT * FROM agents;"
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "SELECT * FROM capabilities;"
```

### Clear Database Tables

#### Method 1: Clear All Data (Keep Tables Structure)

```bash
# Clear all registry data but keep table structure
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "
TRUNCATE TABLE agents RESTART IDENTITY CASCADE;
TRUNCATE TABLE capabilities RESTART IDENTITY CASCADE;
TRUNCATE TABLE registry_events RESTART IDENTITY CASCADE;
SELECT 'Tables cleared successfully' as status;"
```

#### Method 2: Drop All Tables (Registry will recreate them)

```bash
# Drop all tables - registry will recreate on next startup
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "
DROP TABLE IF EXISTS agents CASCADE;
DROP TABLE IF EXISTS capabilities CASCADE;
DROP TABLE IF EXISTS registry_events CASCADE;
SELECT 'Tables dropped successfully' as status;"
```

#### Method 3: Clear Specific Data

```bash
# Clear only agents (keeps capabilities)
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "DELETE FROM agents;"

# Clear only capabilities
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "DELETE FROM capabilities;"

# Clear events older than 1 hour
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "
DELETE FROM registry_events WHERE timestamp < NOW() - INTERVAL '1 hour';"
```

### Database Reset Workflow

```bash
# Complete database reset
# 1. Clear all data
minikube kubectl -- exec -n mcp-mesh mcp-mesh-postgres-0 -- psql -U mcpmesh -d mcpmesh -c "
TRUNCATE TABLE agents RESTART IDENTITY CASCADE;
TRUNCATE TABLE capabilities RESTART IDENTITY CASCADE;
TRUNCATE TABLE registry_events RESTART IDENTITY CASCADE;"

# 2. Restart registry to recreate schema
minikube kubectl -- rollout restart -n mcp-mesh statefulset/mcp-mesh-registry

# 3. Restart agents to re-register
minikube kubectl -- rollout restart -n mcp-mesh deployment/mcp-mesh-hello-world deployment/mcp-mesh-system-agent
```

## ⚠️ Important Notes

1. **Always use `eval $(minikube docker-env)`** before building images for minikube
2. **Use `--no-cache`** when rebuilding images to ensure dependency changes are picked up
3. **Port forwards run in background** - use `pkill -f "kubectl port-forward"` to clean up
4. **Wait for pods to be ready** before testing functionality
5. **Use `minikube kubectl --`** if regular `kubectl` is not available
6. **Check logs first** when debugging issues - they usually reveal the problem
7. **Scale to 0 and back to 1** to simulate service failures for resilience testing

This reference covers all the essential commands for developing, deploying, and testing MCP Mesh in Kubernetes.
