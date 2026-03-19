# Mesh Security

> mTLS encryption, entity trust, credential providers, and certificate management

## Overview

MCP Mesh provides two layers of security:

1. **Registration Trust** — Registry validates agent identity before accepting registration
2. **Agent-to-Agent mTLS** — Every inter-agent call is mutually authenticated

Security is opt-in: local development works with no TLS by default. You can incrementally adopt stricter modes as you move toward production.

## TLS Modes

| Mode       | Description                                                                   | Use Case             |
| ---------- | ----------------------------------------------------------------------------- | -------------------- |
| **off**    | No TLS, plain HTTP. All connections are unencrypted.                          | Local development    |
| **auto**   | Registry verifies certs if presented, allows connections without.             | Transitional rollout |
| **strict** | Mutual TLS required. Registry rejects connections without valid certificates. | Production           |

```bash
# Via flag (enables auto mode with generated certs)
meshctl start --registry-only --tls-auto

# Via environment variable
export MCP_MESH_TLS_MODE=strict
```

## Quick Start: Local TLS

```bash
# Start registry with auto TLS (generates CA + certs)
meshctl start --registry-only --tls-auto -d

# Start agents (inherit TLS config automatically)
meshctl start my_agent.py --tls-auto
```

The `--tls-auto` flag generates a mini-CA under `~/.mcp_mesh/tls/` and configures both the registry and agents automatically.

## Credential Providers

MCP Mesh supports three ways for agents to obtain TLS certificates:

### File Provider (Default)

Reads cert/key from files on disk. Works with cert-manager, static certs, or any PKI that writes PEM files.

```bash
export MCP_MESH_TLS_MODE=auto
export MCP_MESH_TLS_CERT=/etc/certs/agent.pem
export MCP_MESH_TLS_KEY=/etc/certs/agent-key.pem
export MCP_MESH_TLS_CA=/etc/certs/ca.pem
```

### Vault Provider

Fetches certificates from HashiCorp Vault's PKI secrets engine at startup. Certs include DNS + IP SANs for proper hostname verification.

```bash
export MCP_MESH_TLS_MODE=auto
export MCP_MESH_TLS_PROVIDER=vault
export MCP_MESH_VAULT_ADDR=https://vault.example.com:8200
export MCP_MESH_VAULT_PKI_PATH=pki_int/issue/mesh-agent
export VAULT_TOKEN=s.xxxxx
export MCP_MESH_TLS_CA=/etc/certs/vault-ca.pem

# Optional
export MCP_MESH_TRUST_DOMAIN=mcp-mesh.local  # CN suffix (default: mcp-mesh.local)
export MCP_MESH_VAULT_TTL=24h                # Certificate TTL (default: 24h)
```

Certificate CN: `{agent-name}.{trust-domain}` (e.g., `greeter-abc123.mcp-mesh.local`)

### SPIRE Provider

Fetches X.509-SVIDs from the SPIRE agent's Workload API via Unix domain socket. Certs use SPIFFE URI SANs for identity verification.

```bash
export MCP_MESH_TLS_MODE=auto
export MCP_MESH_TLS_PROVIDER=spire
export MCP_MESH_SPIRE_SOCKET=/run/spire/agent/sockets/agent.sock
export MCP_MESH_TLS_CA=/etc/certs/spire-ca.pem
```

In Kubernetes, the SPIRE agent socket is mounted into pods automatically via hostPath or CSI driver. No agent code changes needed.

**SPIFFE-aware TLS**: SPIRE SVIDs use URI SANs (`spiffe://domain/workload`), not DNS/IP SANs. MCP Mesh automatically skips hostname verification for SPIRE certs while still validating the certificate chain against the trust bundle.

### Credential Security

For Vault and SPIRE providers, certificates are:
- Fetched in-memory (never pass through env vars as PEM content)
- Written to secure temp files with 0600 permissions (owner-only read)
- Directory created with 0700 permissions
- On Linux, stored in `/dev/shm` (tmpfs) so private keys never touch disk
- Cleaned up on agent shutdown

## Agent-to-Agent mTLS

When TLS is enabled, all agent-to-agent calls use mutual TLS automatically. The same certificate used for registry registration is used for peer authentication.

- **Python**: `ssl.create_default_context()` with `httpx` client certs
- **TypeScript**: Node.js `tls` module with `undici` Agent
- **Java**: Spring Boot `server.ssl.*` + `SSLContext` for OkHttpClient
- **Go (registry proxy)**: `crypto/tls` with cert chain verification

Self-dependency calls (within the same agent process) skip TLS since there is no network involved.

## Entity Trust

Entities represent organizational CAs whose agents are trusted by the mesh. In multi-org deployments, each organization can have its own CA.

### Register an Entity

```bash
meshctl entity register "partner-corp" --ca-cert /path/to/ca.pem
```

### List Entities

```bash
meshctl entity list
meshctl entity list --json
```

### Revoke an Entity

```bash
meshctl entity revoke "partner-corp" --force
```

Revoking removes the CA from the trust store. In strict mode, agents with revoked CAs are evicted on the next heartbeat cycle.

### Rotate Certificates

```bash
meshctl entity rotate
meshctl entity rotate "partner-corp"
```

Rotation triggers re-registration via the heartbeat 203 protocol. Agents pick up new certificates without downtime.

## Trust Backends

The registry validates agent certificates against trust backends:

| Backend         | Description                                                                       | Use Case                  |
| --------------- | --------------------------------------------------------------------------------- | ------------------------- |
| **localca**     | Built-in mini-CA. Auto-generated with `--tls-auto`.                               | Local development         |
| **filestore**   | Load CAs from filesystem. Supports hot-reload via fsnotify.                       | Static CA deployments     |
| **k8s-secrets** | Load CAs from Kubernetes secrets by label selector.                               | Multi-tenant K8s clusters |
| **spire**       | Validate against SPIFFE trust bundles from the SPIRE Workload API.                | Workload identity         |

Backends can be chained: `MCP_MESH_TRUST_BACKEND=spire,k8s-secrets` (first match wins).

## Environment Variables

### Agent TLS

| Variable                  | Description                                        | Default                                    |
| ------------------------- | -------------------------------------------------- | ------------------------------------------ |
| `MCP_MESH_TLS_MODE`       | TLS mode: `off`, `auto`, `strict`                  | `off`                                      |
| `MCP_MESH_TLS_PROVIDER`   | Credential provider: `file`, `vault`, `spire`      | `file`                                     |
| `MCP_MESH_TLS_CERT`       | Path to client certificate PEM                     | (auto with `--tls-auto`)                   |
| `MCP_MESH_TLS_KEY`        | Path to client private key PEM                     | (auto with `--tls-auto`)                   |
| `MCP_MESH_TLS_CA`         | Path to CA certificate PEM                         | (auto with `--tls-auto`)                   |
| `MCP_MESH_TRUST_DOMAIN`   | Trust domain for cert CN / SPIFFE ID               | `mcp-mesh.local`                           |

### Vault Provider

| Variable                   | Description                           | Default          |
| -------------------------- | ------------------------------------- | ---------------- |
| `MCP_MESH_VAULT_ADDR`      | Vault server URL                      | (required)       |
| `MCP_MESH_VAULT_PKI_PATH`  | PKI issue path                        | (required)       |
| `VAULT_TOKEN`              | Vault authentication token            | (required)       |
| `MCP_MESH_VAULT_TTL`       | Certificate TTL                       | `24h`            |

### SPIRE Provider

| Variable                | Description                          | Default                                    |
| ----------------------- | ------------------------------------ | ------------------------------------------ |
| `MCP_MESH_SPIRE_SOCKET` | Path to SPIRE agent Workload API socket | `/run/spire/agent/sockets/agent.sock`    |

### Registry Trust

| Variable                      | Description                                 | Default          |
| ----------------------------- | ------------------------------------------- | ---------------- |
| `MCP_MESH_TRUST_BACKEND`      | Trust backend(s), comma-separated           | `localca`        |
| `MCP_MESH_TRUST_DIR`          | Directory for filestore/localca backends    | `~/.mcp_mesh/tls`|
| `MCP_MESH_ADMIN_PORT`         | Separate admin API port                     | (disabled)       |
| `MCP_MESH_K8S_NAMESPACE`      | Namespace for k8s-secrets backend           | release namespace|
| `MCP_MESH_K8S_LABEL_SELECTOR` | Label selector for k8s-secrets backend      | `mcp-mesh.io/trust=entity-ca` |

## Admin Port Isolation

```bash
MCP_MESH_ADMIN_PORT=9443 meshctl start --registry-only --tls-auto -d
```

Admin endpoints (`/admin/rotate`, `/admin/entities`) are served only on the admin port when set.

## Kubernetes Deployment

### Helm Values for Vault

```yaml
# Agent chart
mesh:
  tls:
    mode: "auto"
    vault:
      enabled: true
      addr: "https://vault.vault-system:8200"
      pkiPath: "pki_int/issue/mesh-agent"
      tokenSecret: "vault-agent-token"  # K8s secret name
      tokenKey: "token"
    caSecret: "mesh-ca-bundle"
```

### Helm Values for SPIRE

```yaml
# Agent chart
mesh:
  tls:
    mode: "auto"
    spire:
      enabled: true
      socketPath: "/run/spire/agent/sockets/agent.sock"
    caSecret: "spire-ca-bundle"
```

### Helm Values for K8s Secrets Trust Backend

```yaml
# Registry chart
registry:
  security:
    tls:
      enabled: true
      mode: "strict"
    trust:
      backend: "k8s-secrets"
      k8sSecrets:
        namespace: "mcp-mesh"
        labelSelector: "mcp-mesh.io/trust=entity-ca"
```

## See Also

- `meshctl man deployment` - Deployment patterns with TLS
- `meshctl man environment` - All environment variables
- `meshctl man registry` - Registry operations
