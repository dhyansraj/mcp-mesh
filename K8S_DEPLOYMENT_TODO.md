# MCP Mesh Kubernetes Deployment TODO

## ✅ What We Already Have

### 1. **HTTP Wrapper with K8s Health Probes**

- `/health` - Basic health check endpoint
- `/livez` - Liveness probe endpoint
- `/ready` - Readiness probe with tool count
- All three endpoints are properly implemented in the HTTP wrapper

### 2. **Container-Ready Architecture**

- HTTP transport enabled via `MCP_MESH_HTTP_ENABLED=true`
- Auto port assignment or fixed port configuration
- Non-root user support in Dockerfile
- Multi-stage Docker builds for smaller images

### 3. **Basic K8s Manifests**

- Namespace isolation
- Deployment configurations with proper labels
- Service definitions for internal communication
- Resource limits and requests
- Health probe configurations

### 4. **Registry Integration**

- Agents can connect to external registry via `MCP_MESH_REGISTRY_URL`
- Heartbeat mechanism for service registration
- HTTP endpoint updates via heartbeats

## ❌ What's Missing for Production K8s

### 1. **Service Discovery Integration**

- [ ] Automatic endpoint registration using Pod IP instead of localhost
- [ ] Service mesh integration (Istio/Linkerd) examples (SKIP)
- [ ] Headless service support for direct pod-to-pod communication
- [ ] DNS-based service discovery documentation
- [ ] Endpoint slices support for large deployments  (SKIP IF TOO MUCH WORK)

### 2. **ConfigMaps and Secrets**

- [ ] ConfigMap templates for agent configuration
- [ ] Secret management for API keys and credentials
- [ ] External secrets operator integration guide  (SKIP)
- [ ] Environment-specific configuration overlays
- [ ] Hot-reload configuration without pod restart  (SKIP)

### 3. **Persistent Storage for Registry**

- [ ] PersistentVolumeClaim templates for registry data
- [ ] StatefulSet for registry (instead of Deployment)
- [ ] Backup and restore mechanisms with CronJobs  (SKIP)
- [ ] High availability setup with leader election  (SKIP)
- [ ] Database migration strategy  (SKIP)

### 4. **Observability Stack**

- [ ] Prometheus ServiceMonitor definitions
- [ ] Grafana dashboard templates for MCP metrics
- [ ] OpenTelemetry integration for distributed tracing  (SKIP)
- [ ] Structured logging with correlation IDs
- [ ] Custom metrics for MCP protocol operations
- [ ] Alert rules for common failure scenarios

### 5. **Security Hardening**

- [ ] NetworkPolicies for zero-trust networking
- [ ] PodSecurityStandards enforcement
- [ ] Service mesh mTLS configuration
- [ ] RBAC for service accounts with least privilege  (SKIP)
- [ ] Image vulnerability scanning in CI/CD  (SKIP)
- [ ] Admission webhooks for agent validation  (SKIP)
- [ ] Secrets encryption at rest  (SKIP)

### 6. **Advanced Deployment Patterns**

- [ ] Blue-green deployment strategies  (SKIP)
- [ ] Canary deployments with Flagger integration  (SKIP)
- [ ] Progressive rollouts with traffic splitting  (SKIP)
- [ ] Circuit breaker configuration for resilience  (SKIP)
- [ ] Retry and timeout policies per service
- [ ] A/B testing framework for capabilities  (SKIP)

### 7. **Registry High Availability**

- [ ] Multi-replica registry with leader election  (SKIP)
- [ ] Redis/etcd backend for distributed state  (SKIP)
- [ ] Load balancing across registry instances
- [ ] Registry federation for multi-cluster setups  (SKIP)
- [ ] Disaster recovery procedures  (SKIP)

### 8. **Kubernetes-Native Features**

- [ ] Custom Resource Definitions (CRDs) for MCP agents
- [ ] Operator for agent lifecycle management  (SKIP)
- [ ] Validating webhooks for configuration  (SKIP)
- [ ] Service catalog integration  (SKIP)
- [ ] Horizontal Pod Autoscaler configurations  (SKIP)
- [ ] Vertical Pod Autoscaler recommendations  (SKIP)

### 8. **Helm Chart**
- [ ] Helm Chart for Registry
- [ ] Helm Chart for Agents (Python runtime)

## 🔧 Implementation Phases

### Phase 1: Core K8s Support (Immediate Priority)

#### 1.1 Fix Pod IP Registration

```python
# Update agent registration to use Pod IP
endpoint = f"http://{os.getenv('POD_IP', 'localhost')}:{http_port}"
```

#### 1.2 Add ConfigMap Support

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-agent-config
  namespace: mcp-mesh
data:
  agent-config.yaml: |
    capabilities:
      - name: greeting
        version: "1.0.0"
        timeout: 30
    health_interval: 30
    retry_attempts: 3
```

#### 1.3 Implement StatefulSet for Registry

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mcp-registry
  namespace: mcp-mesh
spec:
  serviceName: mcp-registry-headless
  replicas: 3
  selector:
    matchLabels:
      app: mcp-registry
  template:
    spec:
      containers:
        - name: registry
          env:
            - name: REGISTRY_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
```

#### 1.4 Create Helm Chart Structure

```
mcp-mesh-helm/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   └── servicemonitor.yaml
```

### Phase 2: Production Hardening (High Priority)

#### 2.1 Add Prometheus Metrics

```python
# In HTTP wrapper
from prometheus_client import Counter, Histogram, generate_latest

mcp_requests = Counter('mcp_requests_total', 'Total MCP requests', ['method', 'status'])
mcp_latency = Histogram('mcp_request_duration_seconds', 'MCP request latency')

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

#### 2.2 Implement Graceful Shutdown

```python
import signal
import asyncio

async def graceful_shutdown(signum, frame):
    logger.info(f"Received signal {signum}, starting graceful shutdown...")
    # Deregister from registry
    await registry_client.deregister()
    # Stop accepting new requests
    await http_wrapper.stop()
    # Wait for ongoing requests
    await asyncio.sleep(5)
    # Exit
    sys.exit(0)

signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(graceful_shutdown(s, f)))
```

#### 2.3 Add Circuit Breakers

```python
from circuit_breaker import CircuitBreaker

cb = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=30,
    expected_exception=Exception
)

@cb
async def call_remote_service(endpoint: str, payload: dict):
    # Implementation
    pass
```

### Phase 3: Advanced Features (Medium Priority)

#### 3.1 Custom Resource Definition

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: mcpagents.mesh.mcp.io
spec:
  group: mesh.mcp.io
  versions:
    - name: v1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                capabilities:
                  type: array
                  items:
                    type: object
                    properties:
                      name:
                        type: string
                      version:
                        type: string
                replicas:
                  type: integer
                dependencies:
                  type: array
                  items:
                    type: string
```

#### 3.2 Operator Skeleton

```go
// MCP Mesh Operator
type MCPAgentReconciler struct {
    client.Client
    Scheme *runtime.Scheme
}

func (r *MCPAgentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    // 1. Fetch MCPAgent resource
    // 2. Create/update Deployment
    // 3. Create/update Service
    // 4. Register with mesh registry
    // 5. Update status
}
```

### Phase 4: Service Mesh Integration (Lower Priority)

#### 4.1 Istio Integration

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: mcp-agent-routing
spec:
  hosts:
    - mcp-agents
  http:
    - match:
        - headers:
            x-mcp-capability:
              exact: greeting
      route:
        - destination:
            host: hello-world-service
```

#### 4.2 Linkerd Profile

```yaml
apiVersion: linkerd.io/v1beta1
kind: ServiceProfile
metadata:
  name: mcp-agent-profile
spec:
  routes:
    - name: mcp-call
      condition:
        method: POST
        pathRegex: "/mcp"
      timeout: 30s
  retryBudget:
    retryRatio: 0.2
    minRetriesPerSecond: 10
    ttl: 10s
```

## 📋 Implementation Checklist

### Immediate Actions (Week 1)

- [ ] Update HTTP wrapper to use POD_IP environment variable
- [ ] Create basic Helm chart with configurable values
- [ ] Add Prometheus metrics endpoint to HTTP wrapper
- [ ] Document K8s deployment prerequisites
- [ ] Create example with all K8s features enabled

### Short Term (Week 2-3)

- [ ] Implement graceful shutdown handling
- [ ] Add circuit breaker library and patterns
- [ ] Create StatefulSet configuration for registry
- [ ] Add PVC templates for persistent storage
- [ ] Write K8s deployment guide

### Medium Term (Week 4-6)

- [ ] Design and implement CRDs for MCP agents
- [ ] Build basic operator for agent management
- [ ] Create service mesh integration examples
- [ ] Add distributed tracing instrumentation
- [ ] Implement multi-cluster registry federation  (SKIP)

### Long Term (Month 2-3)

- [ ] Production hardening with security policies  (SKIP)
- [ ] Advanced deployment strategies (blue-green, canary)  (SKIP)
- [ ] Complete observability stack integration
- [ ] Performance optimization for large clusters  (SKIP)
- [ ] Disaster recovery and backup automation  (SKIP)

## 🚀 Success Criteria

1. **Basic K8s Deployment** - Agents can run in K8s with proper health checks
2. **Service Discovery** - Agents automatically discover each other via registry
3. **High Availability** - Registry and agents survive node failures
4. **Observability** - Full metrics, logs, and traces available
5. **Security** - Zero-trust networking with mTLS
6. **Automation** - GitOps deployment with Helm/Kustomize
7. **Scalability** - Support 1000+ agents in a cluster

## 📚 Reference Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Ingress       │     │  Service Mesh   │     │   Monitoring    │
│  Controller     │────▶│   (Istio)       │────▶│  (Prometheus)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   MCP Agents    │◀────│  MCP Registry   │────▶│    Database     │
│  (Deployments)  │     │  (StatefulSet)  │     │ (PostgreSQL)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   ConfigMaps    │     │    Secrets      │     │      PVCs       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Notes

- Priority is based on production deployment requirements
- Each phase builds upon the previous one
- Security and observability should be considered throughout
- Performance testing should be done at each phase
- Documentation should be updated continuously
