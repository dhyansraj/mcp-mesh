# TLS with cert-manager for MCP Mesh

This directory contains example configurations for setting up TLS in MCP Mesh
using [cert-manager](https://cert-manager.io/) to automate certificate
lifecycle management.

## Prerequisites

1. **Kubernetes 1.21+** with MCP Mesh core installed
2. **cert-manager v1.12+** installed in your cluster:

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.5/cert-manager.yaml

# Verify it is running
kubectl get pods -n cert-manager
```

3. **MCP Mesh namespace** created:

```bash
kubectl create namespace mcp-mesh
```

## Approaches

### 1. Self-Signed Root CA (Development / Internal)

Best for development, staging, or internal clusters where you control all
clients and do not need publicly trusted certificates.

cert-manager creates a self-signed root CA, then uses that CA to issue
certificates for the registry and agents.

```bash
# Apply cert-manager resources
kubectl apply -f selfsigned-cluster-issuer.yaml \
  -f selfsigned-root-ca.yaml \
  -f selfsigned-ca-issuer.yaml \
  -f selfsigned-registry-cert.yaml \
  -f selfsigned-agent-cert.yaml

# Wait for certificates to be ready
kubectl get certificates -n mcp-mesh -w

# Install MCP Mesh core with TLS enabled
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh \
  -f helm-values-tls.yaml

# Install an agent with TLS
helm install my-agent helm/mcp-mesh-agent -n mcp-mesh \
  -f helm-values-tls.yaml
```

**Files:** [selfsigned-cluster-issuer.yaml](./selfsigned-cluster-issuer.yaml), [selfsigned-root-ca.yaml](./selfsigned-root-ca.yaml), [selfsigned-ca-issuer.yaml](./selfsigned-ca-issuer.yaml), [selfsigned-registry-cert.yaml](./selfsigned-registry-cert.yaml), [selfsigned-agent-cert.yaml](./selfsigned-agent-cert.yaml)

### 2. Let's Encrypt (Public-Facing)

Best for production clusters with public DNS where you need browser-trusted
certificates. Requires a publicly reachable ingress or DNS-01 solver.

```bash
# Create a ClusterIssuer for Let's Encrypt (edit email first)
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: mcp-mesh-letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com        # <-- change this
    privateKeySecretRef:
      name: mcp-mesh-letsencrypt-key
    solvers:
      - http01:
          ingress:
            class: nginx                  # <-- match your ingress class
EOF

# Create a Certificate for the registry ingress
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: mcp-mesh-registry-cert
  namespace: mcp-mesh
spec:
  secretName: mcp-mesh-registry-tls
  issuerRef:
    name: mcp-mesh-letsencrypt
    kind: ClusterIssuer
  dnsNames:
    - registry.mcp-mesh.example.com      # <-- your public DNS name
EOF
```

Then reference `mcp-mesh-registry-tls` in your Helm values or ingress
annotations. For internal agent-to-agent mTLS, combine this with the
self-signed CA approach for mesh-internal traffic.

### 3. HashiCorp Vault PKI (Enterprise)

Best for organizations already running Vault with a PKI secrets engine.
Vault acts as the certificate authority; cert-manager requests certificates
on demand.

```bash
# Apply Vault issuer and certificates
kubectl apply -f vault-issuer.yaml \
  -f vault-registry-cert.yaml \
  -f vault-agent-cert.yaml

# Wait for certificates
kubectl get certificates -n mcp-mesh -w

# Install with TLS values
helm install mcp-core helm/mcp-mesh-core -n mcp-mesh \
  -f helm-values-tls.yaml

helm install my-agent helm/mcp-mesh-agent -n mcp-mesh \
  -f helm-values-tls.yaml
```

**Files:** [vault-issuer.yaml](./vault-issuer.yaml), [vault-registry-cert.yaml](./vault-registry-cert.yaml), [vault-agent-cert.yaml](./vault-agent-cert.yaml)

## Verifying TLS

```bash
# Check certificate status
kubectl get certificates -n mcp-mesh
kubectl describe certificate mcp-mesh-registry-cert -n mcp-mesh

# Inspect the generated secret
kubectl get secret mcp-mesh-registry-tls -n mcp-mesh -o yaml

# Test the registry endpoint with TLS
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000 &
curl --cacert <(kubectl get secret mcp-mesh-ca-secret -n mcp-mesh \
  -o jsonpath='{.data.ca\.crt}' | base64 -d) \
  https://localhost:8000/health
```

## File Reference

| File                                                               | Description                                          |
| ------------------------------------------------------------------ | ---------------------------------------------------- |
| [selfsigned-cluster-issuer.yaml](./selfsigned-cluster-issuer.yaml) | Self-signed ClusterIssuer (bootstraps the root CA)   |
| [selfsigned-root-ca.yaml](./selfsigned-root-ca.yaml)               | Root CA Certificate signed by the self-signed issuer |
| [selfsigned-ca-issuer.yaml](./selfsigned-ca-issuer.yaml)           | Namespace Issuer backed by the root CA               |
| [selfsigned-registry-cert.yaml](./selfsigned-registry-cert.yaml)   | Registry leaf certificate (self-signed CA)           |
| [selfsigned-agent-cert.yaml](./selfsigned-agent-cert.yaml)         | Agent leaf certificate template (self-signed CA)     |
| [vault-issuer.yaml](./vault-issuer.yaml)                           | Vault PKI Issuer                                     |
| [vault-registry-cert.yaml](./vault-registry-cert.yaml)             | Registry certificate via Vault                       |
| [vault-agent-cert.yaml](./vault-agent-cert.yaml)                   | Agent certificate via Vault                          |
| [helm-values-tls.yaml](./helm-values-tls.yaml)                     | Helm values referencing cert-manager secrets         |

## Renewal

cert-manager automatically renews certificates before expiry (default: 2/3
of the certificate lifetime). No manual intervention is required. Monitor
renewal with:

```bash
kubectl get certificaterequests -n mcp-mesh
kubectl get events -n mcp-mesh --field-selector reason=Issuing
```
