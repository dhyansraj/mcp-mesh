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
helm install mcp-core ./mcp-mesh-core \
  -n mcp-mesh --create-namespace \
  --set namespaceCreate=false

# Or with custom values
helm install mcp-core ./mcp-mesh-core \
  -n mcp-mesh --create-namespace \
  --set namespaceCreate=false \
  -f my-values.yaml
```

Deploy into any namespace by changing `-n`. Nothing else needs to change:
every component lands in the release namespace, and short service names
resolve within it.

`--set namespaceCreate=false` is not optional decoration — without it the
install fails on Helm 3 and on any pre-created namespace. See
[Namespace handling](#namespace-handling) for why, for how to adopt a namespace
that already exists, and for what applies to a release that already exists.

### Access Registry

```bash
# Port forward to access registry
kubectl port-forward -n mcp-mesh svc/mcp-core-mcp-mesh-registry 8000:8000

# Check health
curl http://localhost:8000/health
```

### Deploy Agents

After core infrastructure is running, deploy agents:

```bash
# Deploy an agent
helm install my-agent ../mcp-mesh-agent --set agent.script=my_script.py
```

## Namespace handling

Two unrelated mechanisms can create the namespace, and only one of them works
for the namespace a release installs into:

| Mechanism                                                              | What it does                                                                                                                              |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `helm install --create-namespace` (Argo CD: `syncOptions: CreateNamespace=true`) | Creates the `-n` namespace as a plain object that no release owns, before the manifest is applied.                                        |
| `namespaceCreate` (chart value, default `true`)                        | Renders a `Namespace` object **named `global.namespace`, not the release namespace** into the release manifest. Nothing else reads `global.namespace`. |

Helm writes the release secret into the `-n` namespace *before* it applies the
rendered manifest, so a chart-templated `Namespace` can never create the
namespace its own release is installed into. It can only re-declare one that
already exists — and re-declaring an object the release does not own is exactly
what Helm's ownership check rejects. Measured against a live cluster with the
full chart:

| Install shape                                                        | Helm 3.19.0                              | Helm 4.0.1                       |
| ---------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------- |
| `-n <new-ns>`, no `--create-namespace`                               | fails: `namespaces "<ns>" not found`     | fails the same way               |
| `-n <ns> --create-namespace`                                         | fails: `namespaces "<ns>" already exists` | works — Helm 4 adopts the object |
| `kubectl create namespace` first, then install                       | fails: `invalid ownership metadata`      | fails the same way               |
| `-n <ns> --create-namespace --set namespaceCreate=false`             | **works**                                | **works**                        |
| `kubectl create namespace` first, `--set namespaceCreate=false`      | **works**                                | **works**                        |
| `kubectl create namespace` first, `--take-ownership`                 | works                                    | works                            |

Hence the recipe in "Installation": **new installs set `namespaceCreate=false`**
and let `--create-namespace` (or `kubectl create namespace`, or Argo CD) create
the namespace. With `namespaceCreate=false`, `global.namespace` is inert and can
be left alone — there is no second name to keep in sync, and no stray namespace
to create by getting it wrong.

### Adopting a namespace that already exists

If you want the release to own its `Namespace` anyway — GitOps setups that
render the namespace from the chart, for instance — create the namespace first
and install with `--take-ownership` (Helm 3.17+ and Helm 4):

```bash
kubectl create namespace mcp-mesh
helm install mcp-core ./mcp-mesh-core \
  -n mcp-mesh --set global.namespace=mcp-mesh --take-ownership
```

Helm stamps its ownership metadata plus `helm.sh/resource-policy: keep` onto the
existing namespace. `global.namespace` must match `-n`, or the release owns a
`Namespace` object for some *other*, empty namespace — the chart's NOTES warns
when that happens. `--take-ownership` applies to every object in the manifest,
not just the namespace, so use it deliberately.

### Existing releases: do not flip `namespaceCreate` on its own

The `Namespace` is already recorded in the release manifest. Dropping it from
the rendered output makes the next `helm upgrade` **delete the namespace and
everything in it** — agents, Secrets, PVCs the chart never created — while
reporting `STATUS: deployed` and exit `0`. When `global.namespace` matches `-n`,
that is also unrecoverable: the release secret lives in the namespace being
deleted. While the namespace drains, a retried `helm upgrade --install` fails
with `secrets "sh.helm.release.v1.<release>.vN" is forbidden: ... because it is
being terminated`; once it is gone, so is the release history, and
`helm history` reports `release: not found`.

From chart 3.4.0 the rendered `Namespace` carries `helm.sh/resource-policy:
keep`, and Helm reads that policy from the manifest of the revision it is
replacing. So the flip becomes safe only once the release's *current* revision
was rendered by 3.4.0 or later — two separate upgrades:

```bash
# 1. Upgrade to >= 3.4.0, leaving namespaceCreate alone.
helm upgrade mcp-core ./mcp-mesh-core -n mcp-mesh --reuse-values

# Confirm the live namespace picked up the policy before going further.
kubectl get ns mcp-mesh -o jsonpath='{.metadata.annotations}'
#   {"helm.sh/resource-policy":"keep","meta.helm.sh/release-name":...}

# 2. Only then, and only if you want it, drop the Namespace from the release.
helm upgrade mcp-core ./mcp-mesh-core -n mcp-mesh --reuse-values \
  --set namespaceCreate=false
```

There is no hurry to do step 2. Once `keep` is on the namespace, leaving
`namespaceCreate: true` is harmless — `helm uninstall` no longer deletes it (see
"Uninstall").

### Recovering from a failed `--create-namespace` install

On Helm 3, `-n <ns> --create-namespace` with `namespaceCreate: true` fails
**non-atomically**. Helm creates the namespace, then the manifest's `Namespace`
collides with it — but the rest of the manifest has already been applied.
Deployments, the StatefulSet, PVCs, and Secrets are all live and running under a
release marked `failed`:

```
Error: INSTALLATION FAILED: 1 error occurred:
	* namespaces "<ns>" already exists
```

Do **not** try to fix this with `helm upgrade --set namespaceCreate=false`. That
reports `STATUS: deployed` and then deletes the namespace it just deployed into,
cascading the release secret with it. Uninstall the wreckage and reinstall with
the recipe from "Installation":

```bash
helm uninstall mcp-core -n mcp-mesh
helm install mcp-core ./mcp-mesh-core \
  -n mcp-mesh --set namespaceCreate=false
```

The uninstall keeps the namespace (`resource-policy: keep`), so the reinstall
does not need `--create-namespace`. It also keeps the generated PostgreSQL and
Grafana Secrets, Grafana's data PVC, and the StatefulSet's PVC — all
deliberate, and all reused by the reinstall. Delete them by hand if you want
the install to start from scratch.

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
  secret to keep it in sync), or delete the Grafana PVC before upgrading. That
  PVC also carries `helm.sh/resource-policy: keep`, so deleting it means an
  explicit `kubectl delete pvc` (see
  [Adopting `existingSecret`](#adopting-existingsecret-on-an-existing-install)
  for the ordering) — an uninstall/reinstall cycle will not clear it.

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

### Grafana admin password

#### Default: auto-generated admin password

With no credential configured, the Grafana chart generates a random password
into the Secret `<release>-mcp-mesh-grafana-secret` (key: `admin-password`).
The Deployment reads it via `secretKeyRef` — no password is rendered into the
pod spec.

```bash
kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

Lifecycle:

- `helm upgrade` reuses the existing value (the Secret is found via `lookup`).
- The Secret carries `helm.sh/resource-policy: keep`, so Helm never deletes it
  — not on `helm uninstall`, and not on the upgrade that stops rendering it.
  That second case is the one that bites: `persistence.enabled` defaults to
  `true` and Grafana applies `GF_SECURITY_ADMIN_PASSWORD` only on **first
  start**, so the live password lives in `grafana.db` on the volume and this
  Secret is the only record of it. Setting `existingSecret` on a running
  release would otherwise delete the generated password in the same upgrade
  that introduces a new one Grafana ignores — an admin lockout.
  (Reinstalling under the same release name adopts the kept Secret and reuses
  its value via `lookup`.)
- **The annotation does not protect the upgrade that installs it.** Helm
  decides whether to skip a delete by reading the policy off the **live**
  object (and the previous release's stored manifest), and on a release
  installed from a chart that predates the annotation both are annotation-free.
  A release is covered only from the upgrade **after** the one that adds it.
  Check before relying on it:

  ```bash
  kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
    -o jsonpath='{.metadata.annotations}'
  ```
- **Template / GitOps pipelines**: `lookup` needs a live cluster. Pure
  `helm template | kubectl apply` — and renderers such as Argo CD and Flux,
  which build manifests without cluster access — produce a **new random
  password on every render**. The Secret therefore never converges: the
  Application reports permanent drift on
  `<release>-mcp-mesh-grafana-secret`, and syncing it silently rotates the
  admin password. Note that Argo CD caches rendered manifests for an
  unchanged chart version + values, so an Application can look `Synced` until
  something invalidates that cache. Use an existing secret in those
  pipelines (below).

#### Existing secret (recommended for GitOps)

Point the chart at a pre-created Secret. It then renders no Secret of its own,
the Deployment reads `GF_SECURITY_ADMIN_PASSWORD` from yours via
`secretKeyRef`, and the rendered output is byte-stable:

```yaml
mcp-mesh-grafana:
  grafana:
    config:
      existingSecret: "grafana-admin"
      existingSecretPasswordKey: "admin-password" # default
      # Refuse to invent a password instead of generating one, so a values
      # file that loses the reference fails the render rather than starting
      # to rotate the password on every sync.
      generatedSecret: false
```

`generatedSecret: false` without `adminPassword` or `existingSecret` fails at
template time with a message naming both options.

#### Adopting `existingSecret` on an existing install

Two things make this a **two-step** change, not one commit. Grafana applies the
admin password only on first start, so with persistence enabled the effective
password is still the one generated at install time — a different value in your
new secret has no effect. And on a release from a chart without
`helm.sh/resource-policy: keep`, the upgrade that sets `existingSecret` deletes
the generated Secret, destroying the only record of that live password.

1. **Upgrade the chart alone** (no credential changes). This lands the
   annotation on the Secret; its value is untouched. Verify:

   ```bash
   kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
     -o jsonpath='{.metadata.annotations}'
   # must contain "helm.sh/resource-policy":"keep"
   ```

2. **Read the live password and seal it into your secret**, then set
   `existingSecret`. Do this even if you intend to change the password later —
   it is the value Grafana is actually running with:

   ```bash
   kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
     -o jsonpath='{.data.admin-password}' | base64 -d
   ```

To make a *different* password authoritative, change it in Grafana after
adopting the secret — either reset it in place:

```bash
kubectl exec deploy/mcp-core-mcp-mesh-grafana -n mcp-mesh -- \
  grafana-cli admin reset-admin-password <new-password>
```

or reprovision from an empty volume, which requires this order (deleting the
claim blocks on the `pvc-protection` finalizer while a pod has it mounted, and
nothing recreates the claim by itself):

```bash
kubectl scale deploy/mcp-core-mcp-mesh-grafana -n mcp-mesh --replicas=0
kubectl delete pvc mcp-core-mcp-mesh-grafana-pvc -n mcp-mesh
helm upgrade mcp-core helm/mcp-mesh-core -n mcp-mesh ...  # recreates PVC + pod
```

Delete the claim explicitly, as above — `helm uninstall` does not do it for
you. The PVC carries `helm.sh/resource-policy: keep`, so an uninstall leaves
the volume behind and a reinstall adopts it along with the `grafana.db` that
still holds the old password. The annotation only tells Helm to skip the
object; `kubectl delete pvc` is unaffected.

Grafana then initializes from `GF_SECURITY_ADMIN_PASSWORD`, i.e. your secret.
All dashboards, users, and annotations stored in `grafana.db` are lost — the
provisioned datasources and dashboards from this chart come back.

Inline `mcp-mesh-grafana.grafana.config.adminPassword` also stops the
per-render rotation (it is rendered verbatim into the chart-managed Secret),
at the cost of plaintext in your values.

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
helm install mcp-core ./mcp-mesh-core \
  -n mcp-mesh --create-namespace --set namespaceCreate=false \
  -f values.yaml
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
   `namespaceCreate` is enabled — which new installs should not do, see
   [Namespace handling](#namespace-handling)
2. **PostgreSQL** - StatefulSet with persistent storage
3. **Redis** - Deployment with emptyDir (cache-only)
4. **Registry** - StatefulSet connected to PostgreSQL

Only step 1 uses `global.namespace`. Every workload deploys into the release
namespace (`-n`).

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
| Grafana admin       | auto-generated (`generatedSecret: true`) | `<release>-mcp-mesh-grafana-secret` / `admin-password`     | `mcp-mesh-grafana.grafana.config.adminPassword` or `....config.existingSecret` + `existingSecretPasswordKey` (+ `generatedSecret: false` to refuse generation outright — recommended for GitOps renderers, see "Grafana admin password") |
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
helm uninstall mcp-core -n mcp-mesh
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

### What uninstall leaves behind

`helm uninstall` does not reclaim every volume, and the differences are
deliberate:

| Object | Kept? | Why |
| ------ | ----- | --- |
| `<release>-mcp-mesh-grafana-pvc` | yes (`resource-policy: keep`) | Holds `grafana.db`: dashboards, annotations, users, and API keys authored in the UI. `persistence.enabled` defaults to `true`, and a volume the chart enables by default should not be discarded by a command that reports success |
| `<release>-mcp-mesh-grafana-secret` | yes (`resource-policy: keep`) | Only record of the admin password Grafana is actually running with — it is applied on first start and then lives in the volume above |
| `postgres-data-<release>-mcp-mesh-postgres-0` | yes (not release-owned) | Created by the StatefulSet's claim template, so Helm never had it to delete |
| `<release>-mcp-mesh-postgres-credentials` | yes (`resource-policy: keep`) | Must keep matching the provisioned data directory |
| `<release>-mcp-mesh-tempo-pvc` | **no** | A rolling trace buffer, not durable storage: `retention` (default `1h`) prunes it continuously, so what it holds is minutes old and already expiring |
| Namespace | yes (`resource-policy: keep`) | See [Namespace handling](#namespace-handling) |

Reinstalling under the same release name adopts all of the kept objects, with
their data. To reclaim the storage instead, delete the claims yourself — the
annotation only stops Helm, not `kubectl`:

```bash
kubectl delete pvc mcp-core-mcp-mesh-grafana-pvc -n mcp-mesh
kubectl delete pvc postgres-data-mcp-core-mcp-mesh-postgres-0 -n mcp-mesh
```

(While a release is still running, scale the owning workload to `0` first — the
delete otherwise blocks on the `pvc-protection` finalizer until the pod releases
the volume. Grafana's is a Deployment;
[Adopting `existingSecret`](#adopting-existingsecret-on-an-existing-install) has
the full ordering, including the `helm upgrade` that recreates the claim.
PostgreSQL's is a StatefulSet, so scale
`statefulset/mcp-core-mcp-mesh-postgres` instead — its volume claim template
recreates the PVC by itself on the next scale-up.)

The namespace is left in place, whichever way it was created. A release
installed with `namespaceCreate=false` never owned the namespace in the first
place, so there is nothing for Helm to delete. A release that does own one —
`namespaceCreate: true`, or `--take-ownership` — renders it with
`"helm.sh/resource-policy": keep`, so from chart 3.4.0 onward Helm skips the
object on uninstall and the delete cannot cascade to agents, Services, Secrets,
and PVCs the chart never created. Releases installed with an older chart pick
the annotation up automatically on `helm upgrade`; no other action is needed.

Do **not** try to get the same effect by setting `namespaceCreate=false` on an
existing release — on its own that upgrade *deletes* the namespace. See
[Existing releases](#existing-releases-do-not-flip-namespacecreate-on-its-own).

## Values

| Key                | Type   | Default      | Description                          |
| ------------------ | ------ | ------------ | ------------------------------------ |
| `global.namespace` | string | `"mcp-mesh"` | Name of the `Namespace` object rendered by `namespaceCreate`, and inert without it. Nothing else reads it — components always deploy to the release namespace (`-n`) |
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
| `namespaceCreate`  | bool   | `true`       | Render `global.namespace` as a release-owned `Namespace`, annotated `"helm.sh/resource-policy": keep` so uninstall never deletes it. **Set `false` on new installs** — left `true`, the install fails on Helm 3 and on any pre-created namespace. Never flip it to `false` on an existing release in isolation. See [Namespace handling](#namespace-handling) |

## Service Discovery

After installation, agents can connect using these endpoints:

| Service  | Internal URL                      |
| -------- | --------------------------------- |
| Registry | `mcp-core-mcp-mesh-registry:8000` |
| Redis    | `mcp-core-mcp-mesh-redis:6379`    |
| Tempo    | `mcp-core-mcp-mesh-tempo:4317`    |
| Grafana  | `mcp-core-mcp-mesh-grafana:3000`  |

See individual component charts for detailed configuration options.
