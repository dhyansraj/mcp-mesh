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
- **🎯 Service Name Auto-Detection**: Agents detect their service name from `app.kubernetes.io/name` labels

## 🎯 Service Naming Patterns in MCP Mesh

Based on the actual Kubernetes examples in `examples/k8s/base/agents/`, MCP Mesh follows these service naming conventions:

| Component         | Service Name            | Label Value             | Port |
| ----------------- | ----------------------- | ----------------------- | ---- |
| Registry          | `mcp-mesh-registry`     | `mcp-mesh-registry`     | 8000 |
| Hello World Agent | `mcp-mesh-hello-world`  | `mcp-mesh-hello-world`  | 8080 |
| System Agent      | `mcp-mesh-system-agent` | `mcp-mesh-system-agent` | 8080 |
| Your Agent        | `mcp-mesh-{agent-name}` | `mcp-mesh-{agent-name}` | 8080 |

**Critical Pattern**: The service name MUST exactly match the `app.kubernetes.io/name` label value for automatic service detection to work.

## Step-by-Step Guide

### Step 1: Understanding Kubernetes DNS and MCP Mesh Service Names

Kubernetes automatically creates DNS entries for services, and MCP Mesh uses specific naming patterns:

```bash
# DNS naming pattern:
# <service-name>.<namespace>.svc.cluster.local

# 🎯 Actual MCP Mesh service examples:
mcp-mesh-registry.mcp-mesh.svc.cluster.local    # Registry (port 8000)
mcp-mesh-hello-world.mcp-mesh.svc.cluster.local # Hello World Agent (port 8080)
mcp-mesh-system-agent.mcp-mesh.svc.cluster.local # System Agent (port 8080)

# Short forms (within same namespace):
mcp-core-mcp-mesh-registry:8000      # Registry
mcp-mesh-hello-world:8080   # Hello World Agent
mcp-mesh-system-agent:8080  # System Agent

# Test DNS resolution with actual service names
kubectl run -it --rm debug --image=busybox --restart=Never -n mcp-mesh -- \
  nslookup mcp-mesh-registry

kubectl run -it --rm debug --image=busybox --restart=Never -n mcp-mesh -- \
  nslookup mcp-mesh-hello-world
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
    - port: 8081
      targetPort: 8081
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
    - port: 8000
# DNS for pods: registry-0.registry-headless.mcp-mesh.svc.cluster.local
```

### Step 2: Configure Agent Service Discovery

🎯 **Service Name Auto-Detection**: MCP Mesh agents automatically detect their service name from Kubernetes labels, enabling seamless service discovery.

Configure agents using the actual K8s example pattern:

```yaml
# Key service discovery configuration from examples/k8s/base/agents/
env:
  # Kubernetes service discovery - auto-detect from labels
  - name: SERVICE_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['app.kubernetes.io/name']
  - name: NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  # Registry connection - configurable for federated networks
  - name: MCP_MESH_REGISTRY_HOST
    valueFrom:
      configMapKeyRef:
        name: mcp-agent-config
        key: REGISTRY_HOST
  - name: MCP_MESH_REGISTRY_PORT
    valueFrom:
      configMapKeyRef:
        name: mcp-agent-config
        key: REGISTRY_PORT
```

Corresponding agent code with automatic service name detection:

```python
# agent_discovery.py
import os
import requests
import mesh

class ServiceDiscovery:
    def __init__(self):
        # Service name auto-detected from K8s labels
        self.service_name = os.getenv('SERVICE_NAME')  # e.g., "mcp-mesh-hello-world"
        self.namespace = os.getenv('NAMESPACE', 'mcp-mesh')
        self.registry_host = os.getenv('MCP_MESH_REGISTRY_HOST', 'mcp-mesh-registry')
        self.registry_port = os.getenv('MCP_MESH_REGISTRY_PORT', '8000')
        self.registry_url = f"http://{self.registry_host}:{self.registry_port}"

    def discover_by_capability(self, capability):
        """Discover agents by capability through registry"""
        response = requests.get(
            f"{self.registry_url}/agents",
            params={"capability": capability}
        )
        return response.json()

    def discover_by_k8s_service(self, service_name):
        """Direct K8s service discovery using service name"""
        # Use Kubernetes DNS with actual port 8080
        k8s_endpoint = f"http://{service_name}.{self.namespace}:8080"
        return k8s_endpoint

    def get_my_service_url(self):
        """Get this agent's own service URL"""
        return f"http://{self.service_name}.{self.namespace}:8080"

@mesh.agent(name="discovery-aware")
class DiscoveryAwareAgent:
    pass

@mesh.tool(
    capability="discovery_aware",
    dependencies=["weather_service", "data_processor"]
)
def discovery_example(weather_service=None, data_processor=None):
    discovery = ServiceDiscovery()

    # Method 1: Use injected dependencies (recommended)
    if weather_service:
        weather_data = weather_service("London")

    # Method 2: Manual discovery through registry
    weather_agents = discovery.discover_by_capability("weather")

    # Method 3: Direct K8s service call using known service names
    hello_world_url = discovery.discover_by_k8s_service("mcp-mesh-hello-world")
    system_agent_url = discovery.discover_by_k8s_service("mcp-mesh-system-agent")

    # Method 4: Get own service URL
    my_url = discovery.get_my_service_url()

    return {
        "injected": weather_data if weather_service else None,
        "registry": weather_agents,
        "hello_world_endpoint": hello_world_url,
        "system_agent_endpoint": system_agent_url,
        "my_service_url": my_url
    }
```

### Step 3: Implement Service Registration

🎯 **Automatic Registration**: Based on the actual K8s examples, agents use automatic service name detection and registration.

```yaml
# agent-deployment-with-registration.yaml - Following actual patterns
apiVersion: apps/v1
kind: Deployment
metadata:
  name: analytics-agent
  namespace: mcp-mesh
  labels:
    app.kubernetes.io/name: analytics-agent # ← Key: This becomes SERVICE_NAME
    app.kubernetes.io/component: agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: analytics-agent
      app.kubernetes.io/component: agent
  template:
    metadata:
      labels:
        app.kubernetes.io/name: analytics-agent # ← Critical for auto-detection
        app.kubernetes.io/component: agent
    spec:
      containers:
        - name: agent
          image: mcp-mesh-base:latest
          command: ["python", "/app/agent.py"]
          ports:
            - name: http
              containerPort: 8080 # ← Standard port 8080
              protocol: TCP
          env:
            # Registry connection - configurable for federated networks
            - name: MCP_MESH_REGISTRY_HOST
              valueFrom:
                configMapKeyRef:
                  name: mcp-agent-config
                  key: REGISTRY_HOST # "mcp-mesh-registry"
            - name: MCP_MESH_REGISTRY_PORT
              valueFrom:
                configMapKeyRef:
                  name: mcp-agent-config
                  key: REGISTRY_PORT # "8000"
            # HTTP server binding - bind to all interfaces
            - name: HOST
              value: "0.0.0.0"
            # 🎯 Kubernetes service discovery - auto-detect from labels
            - name: SERVICE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.labels['app.kubernetes.io/name']
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            # Agent identification
            - name: MCP_MESH_AGENT_NAME
              value: "analytics-agent"
            # Fallback pod IP for backward compatibility
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          envFrom:
            - configMapRef:
                name: mcp-agent-config
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 5
---
# 🎯 Service matches the deployment label exactly
apiVersion: v1
kind: Service
metadata:
  name: analytics-agent # ← Matches app.kubernetes.io/name
  namespace: mcp-mesh
  labels:
    app.kubernetes.io/name: analytics-agent
    app.kubernetes.io/component: agent
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 8080
      targetPort: http
      protocol: TCP
  selector:
    app.kubernetes.io/name: analytics-agent
    app.kubernetes.io/component: agent
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

| Environment Variable     | Description                      | Default           | Example                       |
| ------------------------ | -------------------------------- | ----------------- | ----------------------------- |
| `SERVICE_NAME`           | K8s service name (auto-detected) | from labels       | mcp-mesh-hello-world          |
| `NAMESPACE`              | Pod namespace (auto-detected)    | from fieldRef     | mcp-mesh                      |
| `MCP_MESH_REGISTRY_HOST` | Registry service name            | mcp-mesh-registry | mcp-mesh-registry             |
| `MCP_MESH_REGISTRY_PORT` | Registry service port            | 8000              | 8000                          |
| `MCP_MESH_REGISTRY_URL`  | Complete registry URL            | auto-constructed  | http://mcp-core-mcp-mesh-registry:8000 |
| `MCP_MESH_AGENT_NAME`    | Agent logical name               | manual            | hello-world, system-agent     |
| `HOST`                   | HTTP binding address             | 0.0.0.0           | 0.0.0.0                       |

## Examples

### Example 1: Service Name-Based Discovery (Real K8s Pattern)

```python
# real_k8s_discovery.py - Based on actual examples/k8s/base/agents/
import os
import requests
import socket
from functools import lru_cache
from kubernetes import client, config

class K8sServiceDiscovery:
    def __init__(self):
        # Load K8s config
        if os.path.exists('/var/run/secrets/kubernetes.io'):
            config.load_incluster_config()
        else:
            config.load_kube_config()

        self.v1 = client.CoreV1Api()
        # 🎯 Auto-detected from environment (matches real examples)
        self.service_name = os.getenv('SERVICE_NAME')  # e.g., "mcp-mesh-hello-world"
        self.namespace = os.getenv('NAMESPACE', 'mcp-mesh')
        self.registry_host = os.getenv('MCP_MESH_REGISTRY_HOST', 'mcp-mesh-registry')
        self.registry_port = os.getenv('MCP_MESH_REGISTRY_PORT', '8000')
        self.registry_url = f"http://{self.registry_host}:{self.registry_port}"

    def get_known_service_endpoints(self):
        """Get all known MCP Mesh agent service endpoints"""
        # 🎯 Based on actual service names from K8s examples
        known_services = {
            'hello-world': 'mcp-mesh-hello-world',
            'system-agent': 'mcp-mesh-system-agent',
            'registry': 'mcp-mesh-registry'
        }

        endpoints = {}
        for logical_name, service_name in known_services.items():
            endpoints[logical_name] = {
                'url': f"http://{service_name}.{self.namespace}:8080",
                'service_name': service_name,
                'dns': f"{service_name}.{self.namespace}.svc.cluster.local"
            }
        return endpoints

    @lru_cache(maxsize=128)
    def discover_service(self, service_name, capability=None):
        """Discover service using actual K8s patterns"""
        endpoints = []

        # Method 1: Direct service name (most reliable)
        try:
            svc = self.v1.read_namespaced_service(service_name, self.namespace)
            if svc.spec.cluster_ip:
                endpoints.append({
                    'url': f"http://{svc.spec.cluster_ip}:8080",
                    'source': 'kubernetes-service',
                    'type': 'service',
                    'service_name': service_name
                })
        except:
            pass

        # Method 2: Registry discovery for capabilities
        if capability and self.registry_url:
            try:
                resp = requests.get(
                    f"{self.registry_url}/agents",
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

        # Method 3: DNS resolution (fallback)
        if not endpoints:
            try:
                ip = socket.gethostbyname(f"{service_name}.{self.namespace}")
                endpoints.append({
                    'url': f"http://{ip}:8080",
                    'source': 'dns',
                    'type': 'resolved',
                    'service_name': service_name
                })
            except:
                pass

        return endpoints

    def call_hello_world_agent(self):
        """Example: Call hello-world agent using service name"""
        url = "http://mcp-mesh-hello-world.mcp-mesh:8080/health"
        response = requests.get(url)
        return response.json()

    def call_system_agent(self):
        """Example: Call system agent using service name"""
        url = "http://mcp-mesh-system-agent.mcp-mesh:8080/health"
        response = requests.get(url)
        return response.json()
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

### Issue 1: Service Name Not Auto-Detected

**Symptoms**: SERVICE_NAME environment variable is empty or incorrect

**Cause**: Missing or incorrect label configuration

**Solution**:

```yaml
# Ensure correct label structure
metadata:
  labels:
    app.kubernetes.io/name: mcp-mesh-hello-world # ← Must match service name
    app.kubernetes.io/component: agent
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: mcp-mesh-hello-world # ← Critical: Must be identical
        app.kubernetes.io/component: agent
```

### Issue 2: Service Discovery DNS Failures

**Symptoms**: Can't resolve service names like "mcp-mesh-registry"

**Cause**: DNS configuration or service naming issues

**Solution**:

```yaml
# Fix DNS configuration
spec:
  dnsPolicy: ClusterFirst
  dnsConfig:
    options:
      - name: ndots
        value: "1"
      - name: single-request-reopen
# Verify service names match exactly:
# Service: metadata.name: mcp-mesh-hello-world
# Deployment: app.kubernetes.io/name: mcp-mesh-hello-world
```

### Issue 3: Registry Connection Failures

**Symptoms**: Agents can't connect to "http://mcp-core-mcp-mesh-registry:8000"

**Cause**: Registry service not ready or wrong configuration

**Solution**:

```yaml
# Verify registry service configuration matches examples
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-agent-config
  namespace: mcp-mesh
data:
  REGISTRY_HOST: "mcp-mesh-registry" # ← Must match service name
  REGISTRY_PORT: "8000" # ← Must match service port
  MCP_MESH_REGISTRY_URL: "http://mcp-core-mcp-mesh-registry:8000"

# Add init container to wait for registry
spec:
  initContainers:
    - name: wait-for-registry
      image: busybox:1.35
      command: ["sh", "-c"]
      args:
        - |
          until nc -z mcp-mesh-registry 8000; do
            echo "Waiting for registry..."
            sleep 2
          done
```

For more issues, see the [section troubleshooting guide](./05-troubleshooting.md).

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

- 🔑 **SERVICE_NAME auto-detection**: Uses `metadata.labels['app.kubernetes.io/name']` from pod labels
- 🔑 **Standard service naming**: Services named like `mcp-mesh-hello-world`, `mcp-mesh-system-agent`
- 🔑 **Port standardization**: Agents use port 8080, registry uses port 8000
- 🔑 **ConfigMap-based registry config**: Host and port configurable via `mcp-agent-config`
- 🔑 **Automatic service creation**: Each agent deployment includes matching service
- 🔑 **Field reference injection**: Namespace and service name injected from Kubernetes metadata

## Next Steps

Let's troubleshoot common Kubernetes deployment issues.

Continue to [Troubleshooting K8s Deployments](./05-troubleshooting.md) →

---

💡 **Tip**: Use `kubectl exec -it <pod> -- cat /etc/resolv.conf` to check DNS configuration inside pods

📚 **Reference**: [Kubernetes DNS Documentation](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)

🧪 **Try It**: Implement a custom service discovery mechanism that combines Kubernetes services with MCP Mesh capabilities
