# Minikube Setup

> Set up a local Kubernetes cluster with Minikube for MCP Mesh development and testing

## Overview

Minikube provides a local Kubernetes cluster perfect for developing and testing MCP Mesh deployments before moving to production. This guide covers installing Minikube, configuring it for MCP Mesh requirements, and optimizing performance for local development.

We'll set up a cluster with sufficient resources, enable necessary addons, and prepare the environment for deploying MCP Mesh components.

## Key Concepts

- **Minikube**: Local Kubernetes implementation for development
- **Drivers**: Virtualization backends (Docker, VirtualBox, HyperKit)
- **Addons**: Additional Kubernetes features (ingress, metrics-server)
- **Profiles**: Multiple cluster configurations
- **Resource Allocation**: CPU, memory, and disk configuration

## Step-by-Step Guide

### Step 1: Install Minikube

Choose your platform and install Minikube:

#### macOS

```bash
# Using Homebrew
brew install minikube

# Or direct download
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-darwin-amd64
sudo install minikube-darwin-amd64 /usr/local/bin/minikube
```

#### Linux

```bash
# Download and install
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# For ARM64
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-arm64
sudo install minikube-linux-arm64 /usr/local/bin/minikube
```

#### Windows

```powershell
# Using Chocolatey
choco install minikube

# Or using installer
# Download from: https://github.com/kubernetes/minikube/releases/latest
```

Verify installation:

```bash
minikube version
```

### Step 2: Choose and Configure Driver

Select the best driver for your system:

#### Docker Driver (Recommended)

```bash
# Ensure Docker is running
docker version

# Set Docker as default driver
minikube config set driver docker
```

#### VirtualBox Driver

```bash
# Install VirtualBox first
# Then set as driver
minikube config set driver virtualbox
```

#### Platform-Specific Drivers

```bash
# macOS: HyperKit
minikube config set driver hyperkit

# Windows: Hyper-V (requires admin)
minikube config set driver hyperv

# Linux: KVM2
minikube config set driver kvm2
```

### Step 3: Start Minikube with MCP Mesh Requirements

Create a cluster with appropriate resources:

```bash
# Start with recommended settings
minikube start \
  --cpus=4 \
  --memory=8192 \
  --disk-size=40g \
  --kubernetes-version=v1.25.0 \
  --addons=ingress,metrics-server,dashboard \
  --extra-config=apiserver.enable-admission-plugins="LimitRanger,ResourceQuota"

# For development with limited resources
minikube start \
  --cpus=2 \
  --memory=4096 \
  --disk-size=20g

# For testing production-like setup
minikube start \
  --cpus=6 \
  --memory=16384 \
  --disk-size=100g \
  --nodes=3
```

Monitor startup:

```bash
# Watch cluster status
minikube status

# View cluster info
kubectl cluster-info
```

### Step 4: Configure Minikube for MCP Mesh

Enable required features and addons:

```bash
# Enable ingress for external access
minikube addons enable ingress

# Enable metrics for monitoring
minikube addons enable metrics-server

# Enable dashboard for visualization
minikube addons enable dashboard

# Enable registry for local image storage
minikube addons enable registry

# List all addons
minikube addons list
```

Configure Docker to use Minikube's registry:

```bash
# Point Docker to Minikube's Docker daemon
eval $(minikube docker-env)

# Now Docker commands use Minikube's Docker
docker ps

# Build images directly in Minikube
docker build -t mcp-mesh/agent:local .
```

### Step 5: Set Up Storage

Configure persistent storage for stateful components:

```bash
# Check default storage class
kubectl get storageclass

# Create a PersistentVolume for testing
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mcp-mesh-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /data/mcp-mesh
  storageClassName: standard
EOF

# Verify storage
kubectl get pv
```

## Configuration Options

| Option        | Description            | Default | Recommended       |
| ------------- | ---------------------- | ------- | ----------------- |
| `--cpus`      | Number of CPUs         | 2       | 4                 |
| `--memory`    | Memory allocation (MB) | 2048    | 8192              |
| `--disk-size` | Disk size              | 20g     | 40g               |
| `--nodes`     | Number of nodes        | 1       | 1 (dev), 3 (test) |
| `--driver`    | Virtualization driver  | auto    | docker            |

## Examples

### Example 1: Development Profile

Create a lightweight development cluster:

```bash
# Create development profile
minikube start -p mcp-dev \
  --cpus=2 \
  --memory=4096 \
  --disk-size=20g \
  --kubernetes-version=v1.25.0

# Create namespace
kubectl create namespace mcp-mesh

# Set default namespace
kubectl config set-context --current --namespace=mcp-mesh

# Verify setup
kubectl get nodes
kubectl get ns
```

### Example 2: Production-Like Profile

Create a multi-node cluster for testing:

```bash
# Create production-like profile
minikube start -p mcp-prod \
  --cpus=6 \
  --memory=16384 \
  --disk-size=100g \
  --nodes=3 \
  --kubernetes-version=v1.25.0 \
  --extra-config=kubelet.max-pods=110 \
  --extra-config=apiserver.enable-admission-plugins="PodSecurityPolicy"

# Label nodes for workload placement
kubectl label nodes mcp-prod-m02 node-role.kubernetes.io/worker=true
kubectl label nodes mcp-prod-m03 node-role.kubernetes.io/worker=true

# Add taints for control plane
kubectl taint nodes mcp-prod control-plane=true:NoSchedule
```

## Best Practices

1. **Resource Planning**: Allocate at least 4GB RAM for MCP Mesh
2. **Profile Management**: Use profiles for different environments
3. **Image Caching**: Pre-pull images to speed up deployments
4. **Addon Selection**: Only enable necessary addons to save resources
5. **Regular Cleanup**: Delete unused clusters to free resources

## Common Pitfalls

### Pitfall 1: Insufficient Resources

**Problem**: Pods stuck in Pending state due to resource constraints

**Solution**: Increase cluster resources:

```bash
# Stop current cluster
minikube stop

# Start with more resources
minikube start --cpus=4 --memory=8192

# Or resize existing cluster (experimental)
minikube config set memory 8192
minikube config set cpus 4
minikube stop && minikube start
```

### Pitfall 2: Image Pull Errors

**Problem**: Kubernetes can't pull Docker images built locally

**Solution**: Use Minikube's Docker daemon:

```bash
# Configure Docker to use Minikube
eval $(minikube docker-env)

# Build image in Minikube
docker build -t mcp-mesh/agent:local .

# Use in Kubernetes with imagePullPolicy: Never
kubectl run test --image=mcp-mesh/agent:local --image-pull-policy=Never
```

## Testing

### Verify Cluster Health

```bash
#!/bin/bash
# test_minikube_setup.sh

echo "Testing Minikube setup for MCP Mesh..."

# Check cluster status
if ! minikube status | grep -q "Running"; then
  echo "ERROR: Minikube not running"
  exit 1
fi

# Check Kubernetes connectivity
if ! kubectl get nodes | grep -q "Ready"; then
  echo "ERROR: Kubernetes not ready"
  exit 1
fi

# Check required addons
for addon in ingress metrics-server; do
  if ! minikube addons list | grep "$addon" | grep -q "enabled"; then
    echo "WARNING: Addon $addon not enabled"
  fi
done

# Check resources
MIN_CPU=2
MIN_MEM=4096

CURRENT_CPU=$(minikube config get cpus)
CURRENT_MEM=$(minikube config get memory)

if [ "$CURRENT_CPU" -lt "$MIN_CPU" ]; then
  echo "WARNING: CPU allocation ($CURRENT_CPU) below recommended ($MIN_CPU)"
fi

if [ "$CURRENT_MEM" -lt "$MIN_MEM" ]; then
  echo "WARNING: Memory allocation ($CURRENT_MEM) below recommended ($MIN_MEM)"
fi

echo "Minikube setup check complete!"
```

### Performance Test

```bash
# Test cluster performance
kubectl create namespace perf-test

# Deploy test workload
kubectl run perf-test --image=busybox \
  --namespace=perf-test \
  --command -- sh -c "while true; do echo 'Running'; sleep 1; done"

# Measure pod startup time
time kubectl wait --for=condition=ready pod/perf-test -n perf-test

# Cleanup
kubectl delete namespace perf-test
```

## Monitoring and Debugging

### Access Kubernetes Dashboard

```bash
# Start dashboard
minikube dashboard

# Or get URL only
minikube dashboard --url
```

### Monitor Resource Usage

```bash
# Check node resources
kubectl top nodes

# Check pod resources
kubectl top pods -n mcp-mesh

# View Minikube logs
minikube logs

# SSH into Minikube VM
minikube ssh
```

### Debug Networking

```bash
# Test service connectivity
minikube service list

# Get service URL
minikube service mcp-mesh-registry -n mcp-mesh --url

# Test DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup kubernetes
```

## 🔧 Troubleshooting

### Issue 1: Minikube Won't Start

**Symptoms**: `minikube start` fails with error

**Cause**: Driver issues or insufficient resources

**Solution**:

```bash
# Clean up existing cluster
minikube delete

# Try different driver
minikube start --driver=docker

# Check system resources
# macOS: Check Activity Monitor
# Linux: free -h
# Windows: Task Manager
```

### Issue 2: kubectl Connection Refused

**Symptoms**: `kubectl get nodes` returns connection error

**Cause**: kubectl context not set correctly

**Solution**:

```bash
# Set kubectl context
minikube kubectl -- get nodes

# Or update kubectl config
minikube update-context

# Verify context
kubectl config current-context
```

For more issues, see the [section troubleshooting guide](./05-troubleshooting.md).

## ⚠️ Known Limitations

- **Resource Constraints**: Limited by host machine resources
- **Networking**: Some advanced networking features unavailable
- **Multi-node**: Performance overhead for multi-node clusters
- **Storage**: Local storage only, no distributed storage

## 📝 TODO

- [ ] Add kind and k3s alternatives
- [ ] Document WSL2 specific setup
- [ ] Add automated setup script
- [ ] Include resource monitoring dashboard
- [ ] Add IPv6 configuration

## Summary

You now have a local Kubernetes cluster configured for MCP Mesh development:

Key takeaways:

- 🔑 Minikube running with appropriate resources
- 🔑 Required addons enabled for MCP Mesh
- 🔑 Docker configured to build images in Minikube
- 🔑 Storage and networking ready for deployments

## Next Steps

Now let's deploy the MCP Mesh registry to your cluster.

Continue to [Local Registry Configuration](./02-local-registry.md) →

---

💡 **Tip**: Use `minikube tunnel` in a separate terminal to access LoadBalancer services locally

📚 **Reference**: [Minikube Documentation](https://minikube.sigs.k8s.io/docs/)

🧪 **Try It**: Create multiple Minikube profiles for different testing scenarios
