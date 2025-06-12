# Service Discovery in K8s

> Understanding how MCP Mesh agents discover and communicate with each other in Kubernetes

## Overview

Service discovery is crucial for MCP Mesh agents to find and communicate with each other in a dynamic Kubernetes environment. This guide explains how Kubernetes DNS works, how agents register with the MCP Mesh registry, and how to configure service discovery for different deployment patterns.

We'll cover DNS-based discovery, headless services, service mesh integration, and troubleshooting connectivity issues between agents.

## Key Concepts

- **Kubernetes DNS**: Automatic DNS for services and pods
- **Service Types**: ClusterIP, NodePort, LoadBalancer, Headless
- **Endpoints**: Actual pod IPs behind a service
- **Registry Integration**: How MCP Mesh enhances K8s discovery
- **Network Policies**: Controlling inter-agent communication

## Step-by-Step Guide

### Step 1: Understanding Kubernetes DNS

Kubernetes automatically creates DNS entries for services:

```bash
# DNS naming pattern:
# <service-name>.<namespace>.svc.cluster.local

# Examples:
mcp-mesh-registry.mcp-mesh.svc.cluster.local
weather-agent.mcp-mesh.svc.cluster.local

# Short forms (within same namespace):
mcp-mesh-registry
weather-agent

# Test DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -n mcp-mesh -- \
  nslookup mcp-mesh-registry
```

DNS for different service types:

```yaml
# Standard Service (ClusterIP)
apiVersion: v1
kind: Service
metadata:
  name: weather-agent
  namespace: mcp-mesh
spec:
  selector:
    app: weather-agent
  ports:
    - port: 8080
      targetPort: 8080
# DNS: weather-agent.mcp-mesh.svc.cluster.local

---
# Headless Service (for StatefulSets)
apiVersion: v1
kind: Service
metadata:
  name: registry-headless
  namespace: mcp-mesh
spec:
  clusterIP: None # Headless
  selector:
    app: registry
  ports:
    - port: 8080
# DNS for pods: registry-0.registry-headless.mcp-mesh.svc.cluster.local
```

### Step 2: Configure Agent Service Discovery

Configure agents to use both Kubernetes DNS and MCP Mesh registry:

```python
# agent_discovery.py
import os
import requests
from mcp_mesh import mesh_agent

class ServiceDiscovery:
    def __init__(self):
        self.registry_url = os.getenv(
            'MCP_MESH_REGISTRY_URL',
            'http://mcp-mesh-registry:8080'
        )
        self.namespace = os.getenv('POD_NAMESPACE', 'mcp-mesh')

    def discover_by_capability(self, capability):
        """Discover agents by capability through registry"""
        response = requests.get(
            f"{self.registry_url}/api/v1/agents",
            params={"capability": capability}
        )
        return response.json()

    def discover_by_k8s_service(self, service_name):
        """Direct K8s service discovery"""
        # Use Kubernetes DNS
        k8s_endpoint = f"http://{service_name}.{self.namespace}:8080"
        return k8s_endpoint

@mesh_agent(
    capability="discovery_aware",
    dependencies=["weather_service", "data_processor"]
)
def discovery_example(ctx, weather_service=None, data_processor=None):
    discovery = ServiceDiscovery()

    # Method 1: Use injected dependencies (recommended)
    if weather_service:
        weather_data = weather_service("London")

    # Method 2: Manual discovery through registry
    weather_agents = discovery.discover_by_capability("weather")

    # Method 3: Direct K8s service call
    k8s_url = discovery.discover_by_k8s_service("weather-agent")
    response = requests.get(f"{k8s_url}/forecast")

    return {
        "injected": weather_data if weather_service else None,
        "registry": weather_agents,
        "k8s_direct": response.json()
    }
```

### Step 3: Implement Service Registration

Ensure agents register with the MCP Mesh registry:

```yaml
# agent-deployment-with-registration.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: analytics-agent
  namespace: mcp-mesh
spec:
  replicas: 3
  selector:
    matchLabels:
      app: analytics-agent
  template:
    metadata:
      labels:
        app: analytics-agent
        mesh.mcp.io/register: "true"
    spec:
      initContainers:
        # Wait for registry to be available
        - name: wait-for-registry
          image: busybox:1.35
          command: ["sh", "-c"]
          args:
            - |
              until nc -z mcp-mesh-registry 8080; do
                echo "Waiting for registry..."
                sleep 2
              done
      containers:
        - name: agent
          image: mcp-mesh/analytics-agent:latest
          env:
            # Pod information for registration
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            # Registration configuration
            - name: MCP_MESH_REGISTRY_URL
              value: "http://mcp-mesh-registry:8080"
            - name: MCP_MESH_ADVERTISE_ADDRESS
              value: "$(POD_IP):8080"
            - name: MCP_MESH_AGENT_ID
              value: "$(POD_NAME)"
            - name: MCP_MESH_CAPABILITIES
              value: "analytics,reporting"
            - name: MCP_MESH_DEPENDENCIES
              value: "database,cache"
          lifecycle:
            postStart:
              exec:
                command:
                  - /bin/sh
                  - -c
                  - |
                    # Register with mesh on startup
                    curl -X POST ${MCP_MESH_REGISTRY_URL}/api/v1/agents \
                      -H "Content-Type: application/json" \
                      -d '{
                        "id": "'${MCP_MESH_AGENT_ID}'",
                        "address": "'${MCP_MESH_ADVERTISE_ADDRESS}'",
                        "capabilities": ["analytics", "reporting"],
                        "metadata": {
                          "pod": "'${POD_NAME}'",
                          "namespace": "'${POD_NAMESPACE}'"
                        }
                      }'
            preStop:
              exec:
                command:
                  - /bin/sh
                  - -c
                  - |
                    # Deregister on shutdown
                    curl -X DELETE ${MCP_MESH_REGISTRY_URL}/api/v1/agents/${MCP_MESH_AGENT_ID}
```

### Step 4: Configure Headless Services for Direct Pod Access

For scenarios requiring direct pod communication:

```yaml
# headless-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: data-processor-headless
  namespace: mcp-mesh
spec:
  clusterIP: None # Headless service
  selector:
    app: data-processor
  ports:
    - port: 8080
      name: http
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: data-processor
  namespace: mcp-mesh
spec:
  serviceName: data-processor-headless
  replicas: 3
  selector:
    matchLabels:
      app: data-processor
  template:
    metadata:
      labels:
        app: data-processor
    spec:
      containers:
        - name: processor
          image: mcp-mesh/data-processor:latest
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: PROCESSOR_ID
              value: "$(POD_NAME)"
          ports:
            - containerPort: 8080
              name: http
```

Access specific pods:

```python
# Direct pod access
def access_specific_processor(processor_id):
    """Access specific data processor pod"""
    # Pod DNS format for StatefulSet
    pod_dns = f"data-processor-{processor_id}.data-processor-headless.mcp-mesh.svc.cluster.local"

    response = requests.get(f"http://{pod_dns}:8080/status")
    return response.json()

# Access all pods
def access_all_processors():
    """Access all data processor pods"""
    results = []
    for i in range(3):  # Assuming 3 replicas
        pod_dns = f"data-processor-{i}.data-processor-headless.mcp-mesh.svc.cluster.local"
        try:
            response = requests.get(f"http://{pod_dns}:8080/status")
            results.append(response.json())
        except:
            results.append({"error": f"Pod {i} unreachable"})
    return results
```

### Step 5: Implement Network Policies

Control which agents can communicate:

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: agent-communication-policy
  namespace: mcp-mesh
spec:
  # Apply to all agents
  podSelector:
    matchLabels:
      app.kubernetes.io/component: agent
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow from other agents
    - from:
        - namespaceSelector:
            matchLabels:
              name: mcp-mesh
          podSelector:
            matchLabels:
              app.kubernetes.io/component: agent
      ports:
        - protocol: TCP
          port: 8080
    # Allow from registry
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: mcp-mesh-registry
      ports:
        - protocol: TCP
          port: 8080
  egress:
    # Allow to registry
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: mcp-mesh-registry
      ports:
        - protocol: TCP
          port: 8080
    # Allow to other agents
    - to:
        - namespaceSelector:
            matchLabels:
              name: mcp-mesh
          podSelector:
            matchLabels:
              app.kubernetes.io/component: agent
      ports:
        - protocol: TCP
          port: 8080
    # Allow DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
```

## Configuration Options

| Environment Variable      | Description         | Default  | Example            |
| ------------------------- | ------------------- | -------- | ------------------ |
| `MCP_MESH_DISCOVERY_MODE` | Discovery mechanism | registry | kubernetes, hybrid |
| `MCP_MESH_SERVICE_NAME`   | K8s service name    | auto     | weather-agent      |
| `MCP_MESH_NAMESPACE`      | Target namespace    | current  | mcp-mesh           |
| `MCP_MESH_DNS_TIMEOUT`    | DNS lookup timeout  | 5s       | 10s                |
| `MCP_MESH_CACHE_TTL`      | Discovery cache TTL | 60s      | 300s               |

## Examples

### Example 1: Hybrid Discovery Strategy

```python
# hybrid_discovery.py
import os
import requests
import socket
from functools import lru_cache
from kubernetes import client, config

class HybridDiscovery:
    def __init__(self):
        # Load K8s config
        if os.path.exists('/var/run/secrets/kubernetes.io'):
            config.load_incluster_config()
        else:
            config.load_kube_config()

        self.v1 = client.CoreV1Api()
        self.namespace = os.getenv('POD_NAMESPACE', 'mcp-mesh')
        self.registry_url = os.getenv('MCP_MESH_REGISTRY_URL')

    @lru_cache(maxsize=128)
    def discover_service(self, service_name, capability=None):
        """Hybrid discovery using both K8s and registry"""
        endpoints = []

        # Try Kubernetes service discovery
        try:
            svc = self.v1.read_namespaced_service(service_name, self.namespace)
            if svc.spec.cluster_ip:
                endpoints.append({
                    'url': f"http://{svc.spec.cluster_ip}:{svc.spec.ports[0].port}",
                    'source': 'kubernetes',
                    'type': 'service'
                })
        except:
            pass

        # Try registry discovery
        if capability and self.registry_url:
            try:
                resp = requests.get(
                    f"{self.registry_url}/api/v1/agents",
                    params={'capability': capability}
                )
                for agent in resp.json():
                    endpoints.append({
                        'url': agent['endpoint'],
                        'source': 'registry',
                        'type': 'agent',
                        'metadata': agent.get('metadata', {})
                    })
            except:
                pass

        # Try DNS as fallback
        if not endpoints:
            try:
                ip = socket.gethostbyname(f"{service_name}.{self.namespace}")
                endpoints.append({
                    'url': f"http://{ip}:8080",
                    'source': 'dns',
                    'type': 'unknown'
                })
            except:
                pass

        return endpoints
```

### Example 2: Service Mesh Integration

```yaml
# istio-service-entry.yaml
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: mcp-mesh-agents
  namespace: mcp-mesh
spec:
  hosts:
    - "*.agent.mcp-mesh.local"
  ports:
    - number: 8080
      name: http
      protocol: HTTP
  resolution: DNS
  location: MESH_INTERNAL
---
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: agent-routing
  namespace: mcp-mesh
spec:
  hosts:
    - "*.agent.mcp-mesh.local"
  http:
    - match:
        - headers:
            capability:
              exact: weather
      route:
        - destination:
            host: weather-agent.mcp-mesh.svc.cluster.local
    - match:
        - headers:
            capability:
              exact: analytics
      route:
        - destination:
            host: analytics-agent.mcp-mesh.svc.cluster.local
```

## Best Practices

1. **Use Registry Discovery**: More flexible than direct K8s services
2. **Cache Discovery Results**: Reduce registry/DNS load
3. **Implement Fallbacks**: Multiple discovery methods
4. **Health Check Endpoints**: Ensure only healthy agents are discovered
5. **Use Labels**: Consistent labeling for service selection

## Common Pitfalls

### Pitfall 1: DNS Resolution Failures

**Problem**: Agents can't resolve service names

**Solution**: Check DNS configuration:

```bash
# Test DNS from pod
kubectl exec -it <pod-name> -n mcp-mesh -- nslookup kubernetes.default

# Check CoreDNS logs
kubectl logs -n kube-system -l k8s-app=kube-dns

# Verify DNS policy in pod
kubectl get pod <pod-name> -o yaml | grep -A5 dnsPolicy
```

### Pitfall 2: Service Endpoints Not Ready

**Problem**: Service has no endpoints

**Solution**: Verify pod labels match service selector:

```bash
# Check service selector
kubectl get svc <service-name> -o yaml | grep -A5 selector

# Check pod labels
kubectl get pods -l <label-selector> --show-labels

# View endpoints
kubectl get endpoints <service-name>
kubectl describe endpoints <service-name>
```

## Testing

### Service Discovery Test Suite

```python
# test_service_discovery.py
import pytest
import requests
from kubernetes import client, config

class TestServiceDiscovery:
    @classmethod
    def setup_class(cls):
        config.load_kube_config()
        cls.v1 = client.CoreV1Api()
        cls.namespace = "mcp-mesh"

    def test_dns_resolution(self):
        """Test K8s DNS works for services"""
        # Deploy test service
        test_svc = client.V1Service(
            metadata=client.V1ObjectMeta(name="test-dns"),
            spec=client.V1ServiceSpec(
                selector={"app": "test"},
                ports=[client.V1ServicePort(port=8080)]
            )
        )

        self.v1.create_namespaced_service(self.namespace, test_svc)

        # Test DNS resolution from pod
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "dns-test"},
            "spec": {
                "containers": [{
                    "name": "test",
                    "image": "busybox",
                    "command": ["nslookup", "test-dns"]
                }],
                "restartPolicy": "Never"
            }
        }

        # Cleanup
        self.v1.delete_namespaced_service("test-dns", self.namespace)

    def test_registry_discovery(self):
        """Test registry-based discovery"""
        registry_url = "http://mcp-mesh-registry:8080"

        # Register test agent
        agent_data = {
            "id": "test-agent-1",
            "capabilities": ["test-capability"],
            "endpoint": "http://test-agent:8080"
        }

        response = requests.post(
            f"{registry_url}/api/v1/agents",
            json=agent_data
        )
        assert response.status_code == 200

        # Discover by capability
        response = requests.get(
            f"{registry_url}/api/v1/agents",
            params={"capability": "test-capability"}
        )
        agents = response.json()
        assert len(agents) > 0
        assert agents[0]["id"] == "test-agent-1"
```

### Load Test Service Discovery

```bash
#!/bin/bash
# load_test_discovery.sh

NAMESPACE=mcp-mesh
ITERATIONS=1000

echo "Load testing service discovery..."

# Test DNS resolution performance
echo "Testing DNS resolution..."
time for i in $(seq 1 $ITERATIONS); do
  kubectl exec -it test-pod -n $NAMESPACE -- \
    nslookup mcp-mesh-registry.mcp-mesh.svc.cluster.local > /dev/null 2>&1
done

# Test registry discovery performance
echo "Testing registry discovery..."
time for i in $(seq 1 $ITERATIONS); do
  curl -s http://localhost:8080/api/v1/agents?capability=test > /dev/null
done

echo "Load test complete"
```

## Monitoring and Debugging

### Monitor Service Discovery

```bash
# Watch service endpoints
kubectl get endpoints -n mcp-mesh -w

# Monitor DNS queries (if using CoreDNS)
kubectl logs -n kube-system -l k8s-app=kube-dns -f | grep mcp-mesh

# Check service discovery metrics
curl http://mcp-mesh-registry:9090/metrics | grep discovery
```

### Debug Discovery Issues

```bash
# Test service discovery from debug pod
kubectl run -it --rm debug --image=nicolaka/netshoot -n mcp-mesh -- bash

# Inside debug pod:
# DNS tests
nslookup mcp-mesh-registry
dig mcp-mesh-registry.mcp-mesh.svc.cluster.local
host weather-agent

# Network connectivity
ping mcp-mesh-registry
telnet mcp-mesh-registry 8080
curl http://mcp-mesh-registry:8080/health

# Trace network path
traceroute mcp-mesh-registry
```

## 🔧 Troubleshooting

### Issue 1: Intermittent Discovery Failures

**Symptoms**: Agents sometimes can't find each other

**Cause**: DNS cache or registry sync issues

**Solution**:

```yaml
# Disable DNS caching in pod
spec:
  dnsConfig:
    options:
      - name: ndots
        value: "1"
      - name: single-request-reopen
```

### Issue 2: Cross-Namespace Discovery

**Symptoms**: Can't discover services in other namespaces

**Cause**: RBAC or network policy restrictions

**Solution**:

```yaml
# Allow cross-namespace discovery
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: mcp-mesh-discovery
rules:
  - apiGroups: [""]
    resources: ["services", "endpoints"]
    verbs: ["get", "list", "watch"]
---
# Update network policy for cross-namespace
spec:
  egress:
    - to:
        - namespaceSelector: {} # Allow all namespaces
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **DNS TTL**: Kubernetes DNS caching can delay updates
- **Service Types**: ExternalName services don't work with all discovery methods
- **Network Policies**: Can block discovery traffic
- **Pod DNS**: Not available during init containers

## 📝 TODO

- [ ] Add mDNS discovery option
- [ ] Document Consul integration
- [ ] Add service mesh examples (Linkerd)
- [ ] Create discovery performance benchmarks
- [ ] Add multi-cluster discovery

## Summary

You now understand service discovery in Kubernetes for MCP Mesh:

Key takeaways:

- 🔑 Kubernetes DNS provides automatic service discovery
- 🔑 MCP Mesh registry enhances capability-based discovery
- 🔑 Multiple discovery strategies for reliability
- 🔑 Network policies control agent communication

## Next Steps

Let's troubleshoot common Kubernetes deployment issues.

Continue to [Troubleshooting K8s Deployments](./05-troubleshooting.md) →

---

💡 **Tip**: Use `kubectl exec -it <pod> -- cat /etc/resolv.conf` to check DNS configuration inside pods

📚 **Reference**: [Kubernetes DNS Documentation](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)

🧪 **Try It**: Implement a custom service discovery mechanism that combines Kubernetes services with MCP Mesh capabilities
