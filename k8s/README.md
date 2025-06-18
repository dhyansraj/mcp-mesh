# MCP Mesh Kubernetes Configuration

This directory contains Kubernetes manifests for deploying MCP Mesh components using Kustomize.

## Directory Structure

```
k8s/
├── README.md                    # This file
├── base/                        # Base Kubernetes manifests
│   ├── kustomization.yaml       # Base kustomization
│   ├── namespace.yaml           # MCP Mesh namespace
│   ├── agents/
│   │   ├── configmap.yaml       # Agent base configuration
│   │   ├── secret.yaml          # Agent credentials
│   │   ├── configmap-examples.yaml.template      # Agent code template
│   │   ├── example-hello-world-deployment.yaml.template
│   │   └── example-system-agent-deployment.yaml.template
│   ├── registry/
│   │   ├── statefulset.yaml     # Registry StatefulSet
│   │   ├── service.yaml         # Registry service
│   │   ├── service-headless.yaml # StatefulSet headless service
│   │   ├── configmap.yaml       # Registry configuration
│   │   ├── secret.yaml          # Registry credentials
│   │   ├── serviceaccount.yaml  # Service account
│   │   ├── rbac.yaml           # RBAC permissions
│   │   ├── pvc.yaml            # Persistent storage
│   │   └── backup-cronjob.yaml # Database backups
│   ├── postgres/
│   │   ├── postgres-statefulset.yaml # PostgreSQL database
│   │   └── postgres-service.yaml     # Database service
│   └── crds/
│       └── mcpagent-crd.yaml   # Custom Resource Definition
└── overlays/                   # Environment-specific configurations
    ├── dev/
    │   └── kustomization.yaml   # Development environment
    └── prod/
        └── kustomization.yaml   # Production environment
```

## Quick Start

### 1. Deploy Base Infrastructure Only

```bash
# Deploy core infrastructure (registry + database only)
kubectl apply -k k8s/base/

# Check deployment status
kubectl get pods -n mcp-mesh

# Expected output:
# mcp-mesh-postgres-0    1/1     Running
# mcp-mesh-registry-0    1/1     Running
```

### 2. Add Agents Using Examples

To add agents, you need to create deployments that reference the examples:

#### Method 1: Using ConfigMap Generator (Recommended)

```bash
# Create a kustomization that includes agent code from examples
cat > k8s/agents-with-examples.yaml << EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - base/

configMapGenerator:
  - name: agent-code-examples
    files:
      - hello_world.py=examples/simple/hello_world.py
      - system_agent.py=examples/simple/system_agent.py
      - weather_agent.py=examples/advanced/weather_agent.py

# Add your agent deployments here
patchesStrategicMerge:
  - agents-patch.yaml
EOF

# Deploy with agents
kubectl apply -k k8s/agents-with-examples.yaml
```

#### Method 2: Copy and Customize Templates

```bash
# Copy templates and customize
cp k8s/base/agents/example-hello-world-deployment.yaml.template k8s/base/agents/hello-world-deployment.yaml
cp k8s/base/agents/example-system-agent-deployment.yaml.template k8s/base/agents/system-agent-deployment.yaml
cp k8s/base/agents/configmap-examples.yaml.template k8s/base/agents/configmap-examples.yaml

# Create ConfigMap with agent code from examples
kubectl create configmap agent-code-examples \
  --from-file=hello_world.py=examples/simple/hello_world.py \
  --from-file=system_agent.py=examples/simple/system_agent.py \
  --dry-run=client -o yaml > k8s/base/agents/configmap-examples.yaml

# Add deployments to kustomization.yaml
echo "  - agents/configmap-examples.yaml" >> k8s/base/kustomization.yaml
echo "  - agents/hello-world-deployment.yaml" >> k8s/base/kustomization.yaml
echo "  - agents/system-agent-deployment.yaml" >> k8s/base/kustomization.yaml

# Deploy with agents
kubectl apply -k k8s/base/
```

## Using Existing Agent Examples

MCP Mesh provides several ready-to-use agent examples in the `examples/` directory:

### Available Examples

#### Simple Agents (`examples/simple/`)

- **`hello_world.py`** - Basic greeting agent with dependency injection
- **`system_agent.py`** - System monitoring and information agent

#### Advanced Agents (`examples/advanced/`)

- **`weather_agent.py`** - Weather service with external API integration
- **`llm_chat_agent.py`** - LLM-powered chat agent
- **`llm_sampling_agent.py`** - LLM sampling and analysis
- **`system_agent.py`** - Advanced system monitoring with more capabilities

### Deploying Different Agent Types

#### Deploy Simple Agents (Basic Testing)

```bash
# Create deployment with simple agents
cat > k8s/simple-agents.yaml << EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - base/

configMapGenerator:
  - name: agent-code-simple
    files:
      - hello_world.py=examples/simple/hello_world.py
      - system_agent.py=examples/simple/system_agent.py

# Custom agent deployments can be added here
EOF

kubectl apply -k k8s/simple-agents.yaml
```

#### Deploy Advanced Agents (Production Ready)

```bash
# Create deployment with advanced agents
cat > k8s/advanced-agents.yaml << EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - base/

configMapGenerator:
  - name: agent-code-advanced
    files:
      - weather_agent.py=examples/advanced/weather_agent.py
      - llm_chat_agent.py=examples/advanced/llm_chat_agent.py
      - system_agent.py=examples/advanced/system_agent.py

secretGenerator:
  - name: agent-secrets
    literals:
      - WEATHER_API_KEY=your-weather-api-key
      - OPENAI_API_KEY=your-openai-api-key
EOF

kubectl apply -k k8s/advanced-agents.yaml
```

#### Deploy Custom Agents

```bash
# Create your own agent based on examples
cp examples/simple/hello_world.py my_custom_agent.py
# Edit my_custom_agent.py...

# Add to deployment
cat > k8s/custom-agents.yaml << EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - base/

configMapGenerator:
  - name: agent-code-custom
    files:
      - my_agent.py=my_custom_agent.py
      - system_agent.py=examples/simple/system_agent.py
EOF

kubectl apply -k k8s/custom-agents.yaml
```

## Environment-Specific Deployments

### Development Environment

```bash
# Deploy to development environment
kubectl apply -k k8s/overlays/dev/

# Customizes:
# - Namespace: mcp-mesh-dev
# - Reduced replicas
# - Debug configuration
# - Development secrets
```

### Production Environment

```bash
# Deploy to production environment
kubectl apply -k k8s/overlays/prod/

# Customizes:
# - Namespace: mcp-mesh
# - High availability (multiple replicas)
# - Production secrets
# - Resource limits
# - Monitoring enabled
```

## Testing and Validation

### 1. Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n mcp-mesh

# Check services
kubectl get svc -n mcp-mesh

# Check registry logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry -f
```

### 2. Setup Port Forwarding

```bash
# Registry API (for meshctl)
kubectl port-forward -n mcp-mesh svc/mcp-mesh-registry 8000:8000 &

# Agent APIs (if deployed)
kubectl port-forward -n mcp-mesh svc/hello-world-agent 8081:8080 &
kubectl port-forward -n mcp-mesh svc/system-agent 8082:8080 &
```

### 3. Test MCP Function Calls

```bash
# Test hello world function (with dependency injection)
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Test system agent directly
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "get_current_time", "arguments": {}}}' | jq .

# List available tools
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/list", "params": {}}' | jq .
```

### 4. Test with meshctl

```bash
# Build meshctl if not already built
make build

# List all registered agents
./bin/meshctl list agents

# Get agent details
./bin/meshctl get agent hello-world
./bin/meshctl get agent system-agent

# Monitor dependencies
./bin/meshctl dependencies
```

## Scaling and High Availability

### Scale Agents

```bash
# Scale hello-world agent
kubectl scale deployment mcp-mesh-hello-world -n mcp-mesh --replicas=3

# Scale system agent
kubectl scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=2

# Verify scaling
kubectl get pods -n mcp-mesh -l app.kubernetes.io/component=agent
```

### Scale Registry

```bash
# Scale registry for high availability
kubectl scale statefulset mcp-mesh-registry -n mcp-mesh --replicas=3

# Verify registry replicas
kubectl get pods -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry
```

## Resilience Testing

### Test Agent Failure Recovery

```bash
# Simulate agent failure
kubectl scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=0

# Test graceful degradation
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Restore agent
kubectl scale deployment mcp-mesh-system-agent -n mcp-mesh --replicas=1

# Test recovery
sleep 30
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

### Test Registry Resilience

```bash
# Restart registry
kubectl delete pod -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry

# Wait for recovery
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mcp-mesh-registry -n mcp-mesh --timeout=120s

# Test functionality
./bin/meshctl list agents
```

## Monitoring and Observability

### Health Checks

```bash
# Check component health
kubectl get pods -n mcp-mesh
kubectl describe pod <pod-name> -n mcp-mesh

# Health endpoints
curl http://localhost:8000/health  # Registry
curl http://localhost:8081/health  # Hello World Agent
curl http://localhost:8082/health  # System Agent
```

### Logs

```bash
# Registry logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/name=mcp-mesh-registry -f

# Agent logs
kubectl logs -n mcp-mesh -l app.kubernetes.io/component=agent -f

# Database logs
kubectl logs -n mcp-mesh mcp-mesh-postgres-0 -f

# Filter for specific events
kubectl logs -n mcp-mesh -l app.kubernetes.io/component=agent -f | grep -i "inject\|depend\|register"
```

## Customization Examples

### Add Weather Agent

```bash
# Create weather agent deployment
cat > k8s/weather-agent.yaml << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-mesh-weather-agent
  namespace: mcp-mesh
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: mcp-mesh-weather-agent
  template:
    metadata:
      labels:
        app.kubernetes.io/name: mcp-mesh-weather-agent
        app.kubernetes.io/component: agent
    spec:
      containers:
        - name: weather-agent
          image: mcp-mesh-base:latest
          imagePullPolicy: Never
          env:
            - name: MCP_MESH_AGENT_NAME
              value: "weather-service"
            - name: WEATHER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: weather-secrets
                  key: API_KEY
          volumeMounts:
            - name: agent-code
              mountPath: /app/agent.py
              subPath: weather_agent.py
      volumes:
        - name: agent-code
          configMap:
            name: agent-code-advanced
EOF

# Apply the weather agent
kubectl apply -f k8s/weather-agent.yaml
```

### Environment-Specific Patches

```bash
# Create development resource patch
cat > k8s/overlays/dev/dev-resources-patch.yaml << EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-mesh-registry
spec:
  template:
    spec:
      containers:
        - name: registry
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "250m"
EOF

# Add to dev kustomization.yaml
echo "  - dev-resources-patch.yaml" >> k8s/overlays/dev/kustomization.yaml
```

## Troubleshooting

### Common Issues

1. **Pods stuck in Pending state**

   ```bash
   # Check resource constraints
   kubectl describe pod <pod-name> -n mcp-mesh

   # Check node resources
   kubectl top nodes
   ```

2. **Agent registration failures**

   ```bash
   # Check registry connectivity
   kubectl exec -it <agent-pod> -n mcp-mesh -- curl http://mcp-mesh-registry:8000/health

   # Check agent logs
   kubectl logs <agent-pod> -n mcp-mesh
   ```

3. **Image pull errors**

   ```bash
   # For minikube, use local Docker daemon
   eval $(minikube docker-env)
   docker build -t mcp-mesh-base -f docker/agent/Dockerfile.base .
   ```

4. **ConfigMap not found**
   ```bash
   # Create agent code ConfigMap
   kubectl create configmap agent-code-examples \
     --from-file=examples/simple/ \
     -n mcp-mesh
   ```

### Useful Commands

```bash
# Quick status overview
kubectl get all -n mcp-mesh

# Debug pod issues
kubectl describe pod <pod-name> -n mcp-mesh
kubectl logs <pod-name> -n mcp-mesh --previous

# Access pod for debugging
kubectl exec -it <pod-name> -n mcp-mesh -- /bin/sh

# Network debugging
kubectl exec -it <pod-name> -n mcp-mesh -- ping mcp-mesh-registry
kubectl exec -it <pod-name> -n mcp-mesh -- nslookup mcp-mesh-registry

# Port forwarding for debugging
kubectl port-forward -n mcp-mesh <pod-name> <local-port>:<container-port>
```

## Cleanup

```bash
# Remove all MCP Mesh resources
kubectl delete namespace mcp-mesh

# Or remove specific deployment
kubectl delete -k k8s/base/

# Stop port forwards
pkill -f "kubectl port-forward"
```

## Best Practices

1. **Use Kustomize**: Leverage overlays for environment-specific configurations
2. **Agent Code Management**: Use ConfigMaps or init containers for agent code
3. **Secrets Management**: Use Kubernetes secrets or external secret managers
4. **Resource Limits**: Always set resource requests and limits
5. **Health Checks**: Configure proper liveness and readiness probes
6. **Monitoring**: Enable logging and metrics collection
7. **Backup**: Regular database backups using the provided CronJob

## Next Steps

- **Production Setup**: Configure external databases, secrets management, and monitoring
- **Custom Agents**: Create your own agents based on the examples
- **GitOps**: Use ArgoCD or Flux for automated deployments
- **Service Mesh**: Integrate with Istio or Linkerd for advanced networking
- **Observability**: Add Prometheus, Grafana, and distributed tracing

For working examples and more details, see the `examples/k8s/` directory which contains a complete deployment setup.
