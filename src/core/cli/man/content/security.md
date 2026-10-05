# Mesh Security

> mTLS encryption, entity trust, credential providers, and certificate management

## Overview

MCP Mesh provides two layers of security:

1. **Registration Trust** — Registry verifies an agent's trust entity before accepting registration
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

The `--tls-auto` flag generates a mini-CA under `~/.mcp-mesh/tls/` and configures both the registry and agents automatically.

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

The SPIRE provider works for Python and TypeScript agents, not Java: the Java runtime refuses to start with `MCP_MESH_TLS_PROVIDER=spire` whenever TLS is enabled (`auto` or `strict`). A Java agent in a SPIRE deployment uses the file provider with its SVID written to disk by a SPIRE helper (for example `spiffe-helper`), pointing `MCP_MESH_TLS_CERT`, `MCP_MESH_TLS_KEY` and `MCP_MESH_TLS_CA` at the exported certificate, key and trust bundle.

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

The name given to `meshctl entity register` names the CA file. The entity id recorded on agents is that CA's O (else OU), and falls back to the registered name only when the CA has neither. `meshctl entity rotate <entity>` matches the entity id recorded on agents.

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

Rotation triggers re-registration via the heartbeat protocol. The registry responds with 410 (Gone) to force agents to re-register with updated certificates, or 202 (Accepted) when topology changes are detected. Agents pick up new certificates without downtime.

## Trust Backends

The registry validates agent certificates against trust backends:

| Backend         | Description                                                                       | Use Case                  |
| --------------- | --------------------------------------------------------------------------------- | ------------------------- |
| **localca**     | Built-in mini-CA. Auto-generated with `--tls-auto`.                               | Local development         |
| **filestore**   | Load CAs from filesystem. Supports hot-reload via fsnotify.                       | Static CA deployments     |
| **k8s-secrets** | Load CAs from Kubernetes secrets by label selector.                               | Multi-tenant K8s clusters |
| **spire**       | Validate against SPIFFE trust bundles from the SPIRE Workload API.                | Workload identity         |

Backends can be chained: `MCP_MESH_TRUST_BACKEND=spire,k8s-secrets` (first match wins).

The `spire` backend needs a registry built with `go build -tags spire`. The released registry binaries and container images are built without that tag, and refuse to start with `spire` in `MCP_MESH_TRUST_BACKEND`. On a released registry, trust SPIRE-issued agent certificates by exporting the SPIRE trust bundle to a PEM file and loading it with `filestore`.

If a configured backend fails to initialize at startup, the registry refuses to start rather than silently dropping that backend (issue #989).

The registry accepts `off`, `auto` and `strict` for `MCP_MESH_TLS_MODE`, in any case, and refuses to start on any other value. With it set to anything other than `off`, the registry needs at least one trust backend. It refuses to start if `MCP_MESH_TRUST_BACKEND` is empty or if every listed backend is skipped for a missing prerequisite (`localca` and `filestore` need `MCP_MESH_TRUST_DIR`). `meshctl start --tls-auto` configures `localca,filestore` for you.

## Trust Scope

Registration trust is entity-scoped, not agent-scoped. A verified certificate tells the registry which trust entity the caller belongs to; the certificate's CN, SANs and SPIFFE ID are never compared with the `agent_id` being registered.

| Backend         | The entity is                                                              |
| --------------- | -------------------------------------------------------------------------- |
| **filestore**   | The O (else OU, else file name) of the CA the certificate chains to        |
| **k8s-secrets** | The entity annotation (else Secret name) of the CA Secret it chains to     |
| **spire**       | The SPIFFE trust domain, not the SVID's SPIFFE ID                          |
| **localca**     | The O of the agent certificate itself (see below)                          |

The registry records the entity on an agent the first time it registers with a verified certificate. After that, only a caller from the same entity can re-register the agent, send its heartbeats (`POST /heartbeat` and the fast `HEAD /heartbeat/{agent_id}` check), or deregister it (`DELETE /agents/{agent_id}`). A caller from another entity, or a certless caller in `auto` mode, gets 403 (`entity_id mismatch` in the body, except on `HEAD`, which has none). An agent that registered without a certificate has no recorded entity, and any caller can re-register or deregister it.

- Agents sharing a trust entity can register under, or take over, each other's `agent_id`. Taking over an id replaces the agent's endpoint and capabilities in the registry.
- With `filestore`, `k8s-secrets` and `spire`, takeover across entities is blocked.
- To isolate workloads that must not trust each other, give them distinct entity ids, not just separate CA files: two `filestore` CAs with the same O are one entity, as are two CA Secrets with the same entity annotation. For `spire`, use separate trust domains.
- With SPIRE, every workload in one trust domain is one entity, however finely its SPIFFE IDs are assigned.

`localca` is a development backend. It takes the entity from the O field of the agent's own certificate, which whoever issues that certificate controls, so any holder of an entity-CA key under the local root can issue a certificate naming another entity. A certificate with no O names no entity, and the agent registers unclaimed.

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
| `MCP_MESH_TRUST_BACKEND`      | Trust backend(s), comma-separated; required unless TLS mode is `off` | (none; `localca,filestore` with `--tls-auto`) |
| `MCP_MESH_TRUST_DIR`          | Directory for filestore/localca backends    | `~/.mcp-mesh/tls` (local), `/etc/mcp-mesh/trust` (Helm) |
| `MCP_MESH_ADMIN_PORT`         | Separate admin API port                     | (disabled)       |
| `MCP_MESH_ADMIN_TLS`          | Admin port inherits main-port TLS + trust   | `false`          |
| `MCP_MESH_K8S_NAMESPACE`      | Namespace for k8s-secrets backend           | release namespace|
| `MCP_MESH_K8S_LABEL_SELECTOR` | Label selector for k8s-secrets backend      | `mcp-mesh.io/trust=entity-ca` |

## Admin Port

```bash
MCP_MESH_ADMIN_PORT=9443 meshctl start --registry-only --tls-auto -d
```

When set, `/admin/*` (`/admin/rotate`, `/admin/entities`, `/admin/drain`) is served only on this port and the main port returns 404.

By default the admin listener is plain `http://` and applies no client-certificate check, whatever `MCP_MESH_TLS_MODE` is set to. Anyone who can reach the port can call it, and `/admin/rotate` signals every matching healthy agent to rotate its credentials. Restrict the port at the network layer with a NetworkPolicy or equivalent: a separate port is not a security boundary on its own.

### Hardening the admin port

```bash
MCP_MESH_ADMIN_TLS=true
```

The admin listener then uses the registry's certificate and the same `MCP_MESH_TLS_MODE` client-certificate policy as the main port: certless callers pass in `auto` and are rejected with 403 in `strict`.

Two things to know before enabling it. The admin port's scheme becomes `https://`, so every existing caller has to be updated — the `http://` admin URLs in `meshctl man registry` and `meshctl man upgrading` assume the default. And `meshctl` cannot present a client certificate, so with `strict` the admin API is reachable only from a cert-capable client such as `curl --cert`; `meshctl registry drain|resume|status` and `meshctl entity rotate` will return 403. Leave it off if `meshctl` is your drain path before upgrades.

## Docker Compose TLS

```yaml
services:
  registry:
    image: mcpmesh/registry:3.7.1
    command: ["--tls-auto"]
    ports: ["8000:8000"]
    volumes:
      - tls-data:/root/.mcp-mesh/tls

  my-agent:
    environment:
      - MCP_MESH_TLS_MODE=auto
      - MCP_MESH_TLS_CERT=/tls/agent.pem
      - MCP_MESH_TLS_KEY=/tls/agent-key.pem
      - MCP_MESH_TLS_CA=/tls/ca.pem
      - MCP_MESH_REGISTRY_URL=https://registry:8000
    volumes:
      - tls-data:/tls:ro

volumes:
  tls-data:
```

**Gotcha**: The registry's `--tls-auto` generates certs into its volume. Mount the same volume read-only into agents so they share the CA.

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

For Python and TypeScript agents (Java does not support the SPIRE provider):

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

## Migration Path: off → auto → strict

1. **Start with `off`** — Default. Everything works over HTTP. Use for local development.

2. **Enable `auto`** — Registry accepts both TLS and plain connections. Roll out `--tls-auto` on the registry first, then agents one by one. Agents without TLS still work.

   ```bash
   # Registry first
   meshctl start --registry-only --tls-auto -d

   # Then agents (one at a time, verify each)
   meshctl start agent1.py --tls-auto
   ```

3. **Switch to `strict`** — Only after ALL agents have TLS. Registry rejects plain HTTP.

   ```bash
   export MCP_MESH_TLS_MODE=strict
   ```

**Gotcha**: Don't jump to `strict` before all agents have certs — they'll be rejected and evicted on the next heartbeat.

## No Token Alternative

The registry's only enforcement is client-certificate verification, set by `MCP_MESH_TLS_MODE` and checked against the trust backends above. There is no shared-token or API-key alternative: with `MCP_MESH_TLS_MODE=off` the registry accepts any caller.

## Troubleshooting

### Certificate Errors

```bash
# Check if certs exist and are valid
openssl x509 -in /path/to/agent.pem -noout -dates -subject

# Verify cert was signed by the CA
openssl verify -CAfile /path/to/ca.pem /path/to/agent.pem

# Test TLS connection to registry
openssl s_client -connect localhost:8000 -CAfile /path/to/ca.pem
```

### Common Issues

| Symptom | Cause | Fix |
| --- | --- | --- |
| `certificate signed by unknown authority` | Agent's CA doesn't match registry's | Use same CA — share via volume or secret |
| `connection refused` on port 8000 | Registry not listening on TLS | Add `--tls-auto` or set `MCP_MESH_TLS_MODE` |
| Agent evicted immediately | `strict` mode + invalid/expired cert | Check cert dates with `openssl x509 -dates` |
| `SPIRE provider requires build with --features spire` | The agent's native core was built without SPIRE | The released Python and TypeScript packages include it; Java does not support SPIRE (use the file provider) |
| `MCP_MESH_TLS_PROVIDER=spire is not supported by the Java runtime` | A Java agent configured for SPIRE | Use the file provider with the SVID exported to disk, or `vault` |
| `SPIRE backend requires build with -tags spire` | The registry binary was built without SPIRE (released binaries are) | Load the exported SPIRE trust bundle with `filestore`, or build the registry with `-tags spire` |
| 403 `entity_id mismatch` on register, heartbeat or shutdown | The `agent_id` is claimed by another trust entity, or the entity id of a running agent changed (backend order, CA O/OU edit, Secret annotation edit) | Use a distinct agent name, issue the cert from the owning entity, or revert the entity change |

### Debug TLS Handshake

```bash
# Enable debug logging to see TLS details
export MCP_MESH_LOG_LEVEL=DEBUG
meshctl start my_agent.py --tls-auto
# Look for "TLS handshake", "certificate verified", "trust domain" in logs
```

## Production Checklist

- [ ] `MCP_MESH_TLS_MODE=strict` on registry and all agents
- [ ] Credential provider configured (file, vault, or spire) — not `--tls-auto`
- [ ] CA certs distributed to all agents (volume, secret, or SPIRE)
- [ ] `MCP_MESH_ADMIN_PORT` set on registry, and the port restricted by NetworkPolicy (see `MCP_MESH_ADMIN_TLS`)
- [ ] Certificate rotation tested (`meshctl entity rotate`)
- [ ] Vault TTL or SPIRE SVID TTL configured for auto-renewal
- [ ] `--tls-auto` NOT used in production (generates self-signed certs)

## See Also

- `meshctl man deployment` - Deployment patterns with TLS
- `meshctl man environment` - All environment variables
- `meshctl man registry` - Registry operations
