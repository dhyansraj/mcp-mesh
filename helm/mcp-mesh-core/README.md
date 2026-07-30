# MCP Mesh Core Infrastructure

This umbrella chart deploys the core MCP Mesh infrastructure components:

- **MCP Mesh Registry** - Central service registry and discovery
- **PostgreSQL** - Database for registry data
- **Redis** - Distributed tracing stream
- **Tempo** - Trace collection and storage (observability)
- **Grafana** - Observability dashboard (observability)

## Quick Start

### Prerequisites

- Kubernetes 1.19+
- Helm 3.0+

### Installation

```bash
# Install core infrastructure
helm install mcp-mesh-core ./mcp-mesh-core -n mcp-mesh --create-namespace

# Or with custom values
helm install mcp-mesh-core ./mcp-mesh-core -n mcp-mesh --create-namespace -f my-values.yaml
```

`--create-namespace` (or Argo CD's `syncOptions: CreateNamespace=true`) is
**required** when the target namespace does not exist yet, and it creates that
namespace without tying it to the release. `namespaceCreate` is not a substitute:
Helm writes the release secret into the `-n` namespace *before* it applies the
rendered manifest, so a chart-templated `Namespace` can never create the
namespace its own release is installed into — the install fails with
`create: failed to create: namespaces "<name>" not found`. It can only
re-declare a namespace that already exists.

`namespaceCreate` (default `true`) additionally renders a `Namespace` object
into the release. It creates **`global.namespace` (default `mcp-mesh`), not the
release namespace** — the two are independent, so installing with
`-n my-app` while leaving `global.namespace` at its default creates a stray
`mcp-mesh` namespace that nothing is deployed into. Keep the two matching:

```bash
helm install mcp-mesh-core ./mcp-mesh-core \
  -n my-app --create-namespace --set global.namespace=my-app
```

Do not flip `namespaceCreate` to `false` on an existing release — see
"Uninstall" below.

### Access Registry

```bash
# Port forward to access registry
kubectl port-forward -n mcp-mesh svc/mcp-mesh-core-mcp-mesh-registry 8000:8000

# Check health
curl http://localhost:8000/health
```

### Deploy Agents

After core infrastructure is running, deploy agents:

```bash
# Deploy an agent
helm install my-agent ../mcp-mesh-agent --set agent.script=my_script.py
```

## Configuration

### Enable/Disable Components

```yaml
# values.yaml
postgres:
  enabled: true # Set to false to use external PostgreSQL

redis:
  enabled: true # Required for distributed tracing

registry:
  enabled: true # Core component, usually always enabled

grafana:
  enabled: true # Set to false to skip observability UI

tempo:
  enabled: true # Set to false to skip trace collection
```

### Database Configuration

Datastore endpoints and credentials are declared once under `global.*` and
inherited by every consumer: the registry, the UI (when enabled), and the
bundled PostgreSQL provisioning. Per-subchart values (e.g.
`mcp-mesh-registry.registry.database.host`) override the global for that
component only.

#### Default: auto-generated database password

With no credential configured, the bundled postgres chart generates a random
password into the Secret `<release>-mcp-mesh-postgres-credentials` (key:
`password`). Provisioning and every consumer (registry, UI) read it from that
one Secret via `secretKeyRef` — no password is rendered into any manifest.

```bash
kubectl get secret mcp-core-mcp-mesh-postgres-credentials -n mcp-mesh \
  -o jsonpath='{.data.password}' | base64 -d
```

Lifecycle:

- `helm upgrade` reuses the existing value (the Secret is found via `lookup`).
- The Secret carries `helm.sh/resource-policy: keep`: it survives
  `helm uninstall`, exactly like the StatefulSet's PVC does, so a reinstall
  under the same release name keeps matching the provisioned data directory.
- **Template pipelines**: `lookup` needs a live cluster. Pure
  `helm template | kubectl apply` (and GitOps tools that render without
  cluster access) regenerate the value on every render — since PostgreSQL
  only reads `POSTGRES_PASSWORD` at first initialization, that breaks
  consumer auth. Use `helm install`/`helm upgrade`, or set an explicit
  `global.postgres.password` / `global.postgres.existingSecret` in such
  pipelines.
- **Upgrading from charts ≤ 2.4.0 default installs**: earlier defaults
  provisioned the database with a built-in development password. The data
  directory keeps that password, so an upgrade with default values would
  generate a fresh secret that no longer matches. Either keep the old
  credential explicitly (`global.postgres.password=mcpmesh123` — and rotate
  it with `ALTER USER`), or reset the database volume.
  The same applies to Grafana: it applies `GF_SECURITY_ADMIN_PASSWORD` only
  on first start, so with persistence enabled (the default) an upgrade keeps
  the previous built-in `admin` password active and the newly generated
  secret is never applied. Reset it in place
  (`kubectl exec deploy/<release>-mcp-mesh-grafana -- grafana-cli admin
  reset-admin-password <new-password>` — use the generated value from the
  secret to keep it in sync), or delete the Grafana PVC before upgrading.

#### Explicit credentials

```yaml
# values.yaml
global:
  postgres:
    name: "mcpmesh"
    username: "mcpmesh"
    password: "change-me" # wins over the generated secret everywhere

mcp-mesh-postgres:
  persistence:
    enabled: true
    size: 20Gi
    storageClass: "fast-ssd"
```

Or with no plaintext in values, point provisioning and all consumers at one
pre-created secret:

```yaml
global:
  postgres:
    existingSecret: "pg-credentials"
    existingSecretPasswordKey: "password" # must be URL-safe (composed DSNs)
```

This works with the bundled postgres enabled: provisioning consumes the same
key via `secretKeyRef`, so the database is initialized with exactly the
credential every consumer connects with. (`existingSecretUrlKey` — full-DSN
mode — additionally requires `existingSecretPasswordKey`, because
provisioning needs a bare password key stored alongside the DSN.)

### External managed datastores

To use a managed PostgreSQL/Redis (RDS, Cloud SQL, ElastiCache, ...), disable
the bundled subcharts and point `global.*` at the managed endpoints — every
consumer inherits them, no per-subchart overrides needed.

Disabling the bundled Redis (`redis.enabled: false`) is required, not
optional, when setting Redis credentials: it runs without AUTH, so
`global.redis.password` / `global.redis.existingSecret` could never work
against it and the render fails at template time. For PostgreSQL, disabling
the bundled subchart is what makes the external endpoint authoritative;
`global.postgres.existingSecret` itself is also valid *with* the bundled
chart (provisioning consumes the same secret — see Database Configuration
above). When disabling the bundled PostgreSQL, also set
`global.postgres.generatedSecret: false`: nothing creates the auto-generated
Secret anymore, and a configuration without an explicit credential (e.g. an
external database using `trust` auth) would otherwise leave every consumer
referencing a Secret that never exists (pods fail with
`CreateContainerConfigError`).

```yaml
# values.yaml
postgres:
  enabled: false
redis:
  enabled: false

global:
  postgres:
    host: "mydb.abc123.us-east-1.rds.amazonaws.com"
    port: 5432
    name: "mcpmesh"
    username: "mcpmesh"
    sslmode: "require"
    # The bundled chart is disabled, so nothing creates the auto-generated
    # Secret — switch generation off and supply the credential explicitly.
    generatedSecret: false
    # Credential from an existing secret: either a key holding a full
    # postgres:// DSN (existingSecretUrlKey) or just the password
    existingSecret: "pg-credentials"
    existingSecretPasswordKey: "password"
  redis:
    host: "myredis.abc123.cache.amazonaws.com"
    port: 6379
    tls:
      enabled: true # rediss://
    existingSecret: "redis-credentials"
    existingSecretPasswordKey: "redis-password"
```

```bash
helm install mcp-core ./mcp-mesh-core -n mcp-mesh -f values.yaml
```

The separate `mcp-mesh-agent` chart is standalone (not an umbrella subchart),
so Helm does not propagate these globals to it automatically — pass the same
`global.redis` values (e.g. the same values file) to each agent release to
point its trace publishing at the managed Redis.

### Registry Configuration

```yaml
# values.yaml
mcp-mesh-registry:
  registry:
    logging:
      level: "DEBUG"
      format: "json"

  ingress:
    enabled: true
    className: "nginx"
    hosts:
      - host: registry.example.com
        paths:
          - path: /
            pathType: Prefix
```

### Air-gapped / private registry installs

`global.imageRegistry` repoints every image in the stack — the registry, UI,
PostgreSQL, Redis, Grafana, Tempo, and the registry's wait-for-db busybox
init container — to a private registry. `global.imagePullSecrets` adds pull
secrets to every pod spec (merged with each chart's own `imagePullSecrets`,
deduplicated by name):

```yaml
# values.yaml
global:
  imageRegistry: my.registry.internal
  imagePullSecrets:
    - name: my-registry-credentials
```

Repository paths are preserved, so mirror each image to the same path:

| Source image          | Pulled as                                  |
| --------------------- | ------------------------------------------ |
| `mcpmesh/registry`    | `my.registry.internal/mcpmesh/registry`    |
| `mcpmesh/ui`          | `my.registry.internal/mcpmesh/ui`          |
| `postgres`            | `my.registry.internal/postgres`            |
| `redis`               | `my.registry.internal/redis`               |
| `grafana/grafana`     | `my.registry.internal/grafana/grafana`     |
| `grafana/tempo`       | `my.registry.internal/grafana/tempo`       |
| `busybox`             | `my.registry.internal/busybox`             |

Docker Hub library images (`postgres`, `redis`, `busybox`) keep their
single-segment name — mirror them to that same path; the charts do not
rewrite repository paths. Per-component overrides win over the global (e.g.
`mcp-mesh-registry.image.registry`). The standalone `mcp-mesh-agent` chart
honors the same `global.imageRegistry` / `global.imagePullSecrets` values
when passed to each agent release.

### Registry high availability

The registry is stateless when backed by PostgreSQL (the default), so it can
run multi-replica:

```yaml
# values.yaml
mcp-mesh-registry:
  replicaCount: 3
```

That is the only required change. At more than one replica the chart
automatically adds:

- **Soft topology spread** across zones and nodes (`ScheduleAnyway`,
  `maxSkew: 1`) — a no-op on single-node clusters, replica spreading
  wherever real topology exists. Replace with explicit
  `mcp-mesh-registry.topologySpreadConstraints` (or disable via
  `mcp-mesh-registry.defaultTopologySpread.enabled: false`) for hard
  requirements.
- **A PodDisruptionBudget** (`minAvailable: 1`) so node drains keep at least
  one registry running. It never renders at a single replica, where it would
  block drains.

For load-based scaling, enable the HPA instead of a fixed count:

```yaml
mcp-mesh-registry:
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 80
```

Multi-replica and autoscaling require an external database — with
`registry.database.type=sqlite` the template fails, since sqlite is a
single-writer local file.

## Architecture

The core infrastructure follows this deployment pattern:

1. **Namespace** - Creates `global.namespace` (default `mcp-mesh`) when
   `namespaceCreate` is enabled
2. **PostgreSQL** - StatefulSet with persistent storage
3. **Redis** - Deployment with emptyDir (cache-only)
4. **Registry** - StatefulSet connected to PostgreSQL

Only step 1 uses `global.namespace`. Every workload deploys into the release
namespace (`-n`), which is why the two need to match.

## Monitoring

Enable a Prometheus ServiceMonitor on the registry subchart:

```yaml
# values.yaml
mcp-mesh-registry:
  serviceMonitor:
    enabled: true
```

## Security

### Credential summary

No chart ships a usable default password. Every credential is either
auto-generated into a Secret or sourced from one you pre-create:

| Credential          | Default                              | Secret / key                                                  | Override                                                                       |
| ------------------- | ------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| PostgreSQL          | auto-generated, shared by all consumers | `<release>-mcp-mesh-postgres-credentials` / `password`      | `global.postgres.password` or `global.postgres.existingSecret` + `existingSecretPasswordKey` (or `existingSecretUrlKey`) |
| Grafana admin       | auto-generated                       | `<release>-mcp-mesh-grafana-secret` / `admin-password`        | `mcp-mesh-grafana.grafana.config.adminPassword` or `....config.existingSecret` + `existingSecretPasswordKey` |
| Redis               | none (bundled Redis runs without AUTH) | —                                                            | `global.redis.password` / `global.redis.existingSecret` (external Redis only)  |
| UI database         | inherits `global.postgres` (see below) | —                                                            | `mcp-mesh-ui.ui.database.url`                                                  |

### Read-only database role for the UI

The UI only reads. By default (umbrella) it connects with the shared
`global.postgres` credential; for production, give it a dedicated read-only
role. No chart provisions that role — create it once against the registry
database:

```sql
CREATE ROLE mcp_mesh_readonly LOGIN PASSWORD '<password>';
GRANT CONNECT ON DATABASE mcpmesh TO mcp_mesh_readonly;
GRANT USAGE ON SCHEMA public TO mcp_mesh_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_mesh_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_mesh_readonly;
```

then point the UI at it:

```yaml
mcp-mesh-ui:
  ui:
    database:
      url: "postgresql://mcp_mesh_readonly:<password>@mcp-core-mcp-mesh-postgres:5432/mcpmesh?sslmode=disable"
```

### Registry auth

```yaml
# values.yaml
mcp-mesh-registry:
  registry:
    security:
      auth:
        enabled: true
        type: "token"
        tokens:
          - "your-secure-token"
```

## Uninstall

```bash
helm uninstall mcp-mesh-core -n mcp-mesh
```

This removes the core workloads — registry, PostgreSQL, Redis, and, when
enabled, Tempo and Grafana.

There is no mesh data to back up first. The registry's database is **derived
state**: agents re-register on their next heartbeat, so a registry that comes
back empty repopulates itself. Losing it costs a transient topology gap, not
data. Agents also keep serving while the registry is down — dependencies that
are already resolved are never cleared on a registry disconnect (a deliberate
resilience invariant; the runtimes only log the event). What pauses is topology
detection: until the registry is answering heartbeats again, new capabilities
are not discovered, changed ones are not re-resolved, and a client that has not
already resolved an agent cannot look it up.

Application data is the part that needs care. If you pointed your own workloads
at the bundled PostgreSQL or Redis for their own storage — an easy shortcut to
take — that data is yours to protect. It is not derived, and no heartbeat
brings it back. Note that the bundled PostgreSQL keeps its data on a PVC created
by the StatefulSet's volume claim template, which the release does not own, so
`helm uninstall` leaves the volume behind; it is deleting that PVC (or the
namespace around it) that destroys the data. Bundled Redis writes to an
`emptyDir` unless you enable persistence against a PVC you created yourself, so
treat its contents as ephemeral either way.

The namespace is left in place. `namespaceCreate` (default `true`) makes the
release own a `Namespace` object, and deleting a namespace cascades to every
resource in it — agents, Services, Secrets, and PVCs the chart never created.
The namespace template carries `"helm.sh/resource-policy": keep`, so Helm skips
it on uninstall and the cascade cannot happen. Releases installed with an older
chart pick the annotation up automatically on `helm upgrade`; no other action
is needed.

Do **not** set `namespaceCreate=false` on an existing release to get the same
effect. The `Namespace` is already recorded in the release manifest, so
removing it from the rendered output makes the next `helm upgrade` delete the
namespace and everything in it — while reporting `STATUS: deployed` and exit
`0`. When `global.namespace` matches the namespace you pass to `-n`, it is also
unrecoverable: Helm keeps the release secret in the `-n` namespace, which is the
one being deleted, so `helm history` afterward reports `release: not found`. If
the two differ, the release metadata survives in the `-n` namespace — but the
rendered namespace is still deleted, cascade included.

## Values

| Key                | Type   | Default      | Description                          |
| ------------------ | ------ | ------------ | ------------------------------------ |
| `global.namespace` | string | `"mcp-mesh"` | Name of the `Namespace` object rendered by `namespaceCreate`. Nothing else reads it — components always deploy to the release namespace (`-n`), so keep the two matching |
| `global.imageRegistry` | string | `""` | Registry prefix applied to every image (repository paths preserved — see "Air-gapped / private registry installs"); per-component `image.registry` overrides win |
| `global.imagePullSecrets` | list | `[]` | Pull secrets (`- name: ...`) added to every pod spec, merged with each chart's own `imagePullSecrets` and deduplicated by name |
| `global.postgres.*` | object | bundled postgres | PostgreSQL endpoint/credentials inherited by all consumers (`host`, `port`, `name`, `username`, `password`, `sslmode`, `existingSecret`, `existingSecretUrlKey`, `existingSecretPasswordKey`, `tls.caSecret`, `tls.caKey`) |
| `global.postgres.generatedSecret` | bool | `true` | Auto-generate the password into `<release>-mcp-mesh-postgres-credentials` when no `password`/`existingSecret` is set (provisioning and all consumers share it) |
| `global.postgres.generatedSecretName` | string | `""` | Override the generated Secret's name (needed only with name/fullname overrides on the postgres subchart) |
| `global.redis.*`   | object | bundled redis | Redis endpoint/credentials inherited by all consumers (`host`, `port`, `password`, `existingSecret`, `existingSecretUrlKey`, `existingSecretPasswordKey`, `tls.enabled`) |
| `postgres.enabled` | bool   | `true`       | Enable PostgreSQL deployment         |
| `redis.enabled`    | bool   | `true`       | Enable Redis deployment              |
| `registry.enabled` | bool   | `true`       | Enable Registry deployment           |
| `grafana.enabled`  | bool   | `true`       | Enable Grafana deployment            |
| `tempo.enabled`    | bool   | `true`       | Enable Tempo deployment              |
| `namespaceCreate`  | bool   | `true`       | Render `global.namespace` as a release-owned `Namespace`, annotated `"helm.sh/resource-policy": keep` so uninstall never deletes it. Safe to disable at install time; never flip it to `false` on an existing release (see "Uninstall") |

## Service Discovery

After installation, agents can connect using these endpoints:

| Service  | Internal URL                      |
| -------- | --------------------------------- |
| Registry | `mcp-core-mcp-mesh-registry:8000` |
| Redis    | `mcp-core-mcp-mesh-redis:6379`    |
| Tempo    | `mcp-core-mcp-mesh-tempo:4317`    |
| Grafana  | `mcp-core-mcp-mesh-grafana:3000`  |

See individual component charts for detailed configuration options.
