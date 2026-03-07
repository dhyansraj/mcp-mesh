# Mesh Security

> TLS encryption, entity trust, and certificate management for MCP Mesh

## Overview

MCP Mesh supports mutual TLS for agent-registry communication, entity-based trust for multi-org deployments, and certificate rotation without downtime. Security features are opt-in: local development works with no TLS by default, and you can incrementally adopt stricter modes as you move toward production.

## TLS Modes

MCP Mesh supports three TLS modes:

| Mode       | Description                                                                   | Use Case             |
| ---------- | ----------------------------------------------------------------------------- | -------------------- |
| **off**    | No TLS, plain HTTP. All connections are unencrypted.                          | Local development    |
| **auto**   | Registry verifies certs if presented, allows connections without.             | Transitional rollout |
| **strict** | Mutual TLS required. Registry rejects connections without valid certificates. | Production           |

Set the mode with the `--tls-auto` flag (which enables `auto` mode) or the `MCP_MESH_TLS_MODE` environment variable:

```bash
# Via flag
meshctl start --registry-only --tls-auto

# Via environment variable
export MCP_MESH_TLS_MODE=strict
meshctl start --registry-only
```

## Quick Start: Local TLS

```bash
# Start registry with auto TLS
meshctl start --registry-only --tls-auto -d

# Start an agent (picks up TLS config automatically)
meshctl start my_agent.py
```

The `--tls-auto` flag generates a mini-CA under `~/.mcp_mesh/tls/` and configures both the registry and agents automatically. Agents started with `meshctl start` inherit the TLS configuration from the registry, so no additional setup is needed.

## Entity Trust

Entities represent organizational CAs whose agents are trusted by the mesh. In multi-org deployments, each organization or team can have its own CA, and the registry trusts agents presenting certificates signed by any registered entity CA.

### Register an Entity

```bash
meshctl entity register "partner-corp" --ca-cert /path/to/ca.pem
```

This adds the CA certificate to the registry's trust store. Agents presenting certificates signed by this CA will be accepted.

### List Entities

```bash
# Human-readable output
meshctl entity list

# JSON output for scripting
meshctl entity list --json
```

### Revoke an Entity

```bash
meshctl entity revoke "partner-corp" --force
```

Revoking an entity removes its CA from the trust store. In strict mode, agents with certificates signed by the revoked CA are evicted from the mesh on the next heartbeat cycle.

### Rotate Certificates

```bash
# Rotate certificates for all entities
meshctl entity rotate

# Rotate certificates for a specific entity
meshctl entity rotate "partner-corp"
```

Certificate rotation triggers re-registration on the next heartbeat. Agents automatically pick up new certificates without downtime. Agents with revoked CAs are evicted in strict mode.

## Environment Variables

| Variable                 | Description                                                   | Default                            |
| ------------------------ | ------------------------------------------------------------- | ---------------------------------- |
| `MCP_MESH_TLS_MODE`      | TLS mode: `off`, `auto`, or `strict`                          | `off`                              |
| `MCP_MESH_TLS_CERT`      | Path to TLS certificate                                       | (auto-generated with `--tls-auto`) |
| `MCP_MESH_TLS_KEY`       | Path to TLS private key                                       | (auto-generated with `--tls-auto`) |
| `MCP_MESH_TLS_CA`        | Path to CA certificate                                        | (auto-generated with `--tls-auto`) |
| `MCP_MESH_TRUST_BACKEND` | Trust backend: `localca`, `filestore`, `k8s-secrets`, `spire` | `localca`                          |
| `MCP_MESH_TRUST_DIR`     | Trust store directory                                         | `~/.mcp_mesh/tls`                  |
| `MCP_MESH_ADMIN_PORT`    | Separate admin API port                                       | (disabled)                         |
| `MCP_MESH_TLS_PROVIDER`  | Agent TLS provider: `file`, `spire`, `vault`                  | `file`                             |

## Admin Port Isolation

When `MCP_MESH_ADMIN_PORT` is set, admin endpoints (`/admin/rotate`, `/admin/entities`) are served only on the admin port and are not accessible on the main registry port. This prevents agents from accessing admin operations.

```bash
# Run registry with admin port isolation
MCP_MESH_ADMIN_PORT=9443 meshctl start --registry-only --tls-auto -d
```

## Kubernetes TLS

For Kubernetes deployments, TLS is configured through Helm values and integrates with cert-manager. See `meshctl man deployment` for Helm chart configuration and `examples/k8s/tls/` for cert-manager examples.

### Trust Backends

| Backend         | Description                                                                                                                   |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **localca**     | Built-in mini-CA. Default, suitable for development and single-cluster deployments.                                           |
| **filestore**   | Load CA certs from the filesystem. Supports hot-reload via fsnotify when certificates change on disk.                         |
| **k8s-secrets** | Load CAs from Kubernetes secrets by label selector. Useful for multi-tenant clusters where each namespace manages its own CA. |
| **spire**       | SPIFFE/SPIRE integration for workload identity. Provides automatic certificate lifecycle management.                          |

### Agent TLS Providers

| Provider  | Description                                                         |
| --------- | ------------------------------------------------------------------- |
| **file**  | Load cert/key from files or Kubernetes secrets. Default provider.   |
| **spire** | Get workload certificates from the SPIRE agent running on the node. |
| **vault** | Fetch certificates from HashiCorp Vault PKI secrets engine.         |

## See Also

- `meshctl man deployment` - Deployment patterns with TLS
- `meshctl man environment` - All environment variables
- `meshctl man registry` - Registry operations
