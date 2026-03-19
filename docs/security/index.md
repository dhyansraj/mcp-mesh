---
title: Security
description: mTLS, trust management, and credential providers for MCP Mesh
---

# Security

MCP Mesh provides three layers of security for production agent deployments:

```
┌─────────────────────────────────────────────────┐
│  Layer 3: Authorization (WHO can do WHAT)        │
│  Header propagation + application-layer auth     │
├─────────────────────────────────────────────────┤
│  Layer 2: Agent-to-Agent mTLS                    │
│  Every inter-agent call is mutually authenticated│
├─────────────────────────────────────────────────┤
│  Layer 1: Registration Trust                     │
│  Identity verification before joining the mesh   │
└─────────────────────────────────────────────────┘
```

Security is **opt-in** — local development works with no TLS by default. You can incrementally adopt stricter modes as you move toward production.

## TLS Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **off** | No TLS, plain HTTP | Local development |
| **auto** | Registry verifies certs if presented, allows without | Transitional rollout |
| **strict** | mTLS required — registry rejects connections without valid certificates | Production |

## Quick Start

=== "Local Development"

    ```bash
    # Zero-config TLS (auto-generates CA + certs)
    meshctl start --registry-only --tls-auto -d
    meshctl start my_agent.py --tls-auto
    ```

=== "Vault (Production)"

    ```bash
    meshctl start --registry-only -d \
      --env MCP_MESH_TLS_MODE=strict \
      --env MCP_MESH_TLS_CERT=/etc/certs/registry.pem \
      --env MCP_MESH_TLS_KEY=/etc/certs/registry-key.pem

    meshctl start my_agent.py \
      --env MCP_MESH_TLS_MODE=strict \
      --env MCP_MESH_TLS_PROVIDER=vault \
      --env MCP_MESH_VAULT_ADDR=https://vault:8200 \
      --env MCP_MESH_VAULT_PKI_PATH=pki_int/issue/mesh-agent \
      --env VAULT_TOKEN=s.xxxxx
    ```

=== "SPIRE (Workload Identity)"

    ```bash
    meshctl start my_agent.py \
      --env MCP_MESH_TLS_MODE=strict \
      --env MCP_MESH_TLS_PROVIDER=spire \
      --env MCP_MESH_SPIRE_SOCKET=/run/spire/agent/sockets/agent.sock
    ```

## Sections

<div class="grid cards" markdown>

-   :material-shield-lock:{ .lg .middle } **Registration Trust**

    ---

    Registry validates agent identity before accepting registration. Supports file-based certs, Vault PKI, and SPIRE workload identity.

    [:octicons-arrow-right-24: Registration Trust](registration-trust.md)

-   :material-lock:{ .lg .middle } **Agent-to-Agent mTLS**

    ---

    Every inter-agent call is mutually authenticated with TLS certificates. Works across Python, TypeScript, Java, and Go.

    [:octicons-arrow-right-24: Agent-to-Agent mTLS](agent-to-agent-mtls.md)

-   :material-key:{ .lg .middle } **Authorization**

    ---

    Control which agents and users can access capabilities using header propagation and application-layer auth frameworks.

    [:octicons-arrow-right-24: Authorization](authorization.md)

</div>
