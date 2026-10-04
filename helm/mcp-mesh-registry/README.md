# MCP Mesh Registry Helm Chart

This Helm chart deploys the MCP Mesh Registry service on Kubernetes.

## Prerequisites

- Kubernetes 1.21+
- Helm 3.8+
- A PostgreSQL database (the default `registry.database.type`), or
  `registry.database.type: sqlite` for a single replica
- PV provisioner support in the underlying infrastructure (if persistence is enabled)

## Installing the Chart

Most installs get this chart through the `mcp-mesh-core` umbrella, which
bundles PostgreSQL and wires it up. Standalone, point it at your database. To
install the chart with the release name `mcp-registry`:

```bash
helm install mcp-registry ./helm/mcp-mesh-registry \
  --set registry.database.host=postgres.database.svc.cluster.local \
  --set registry.database.password=change-me
```

## Uninstalling the Chart

To uninstall the `mcp-registry` deployment:

```bash
helm uninstall mcp-registry
```

## Configuration

The following table lists the configurable parameters of the MCP Mesh Registry chart and their default values.

### General Configuration

| Parameter                  | Description                                                                | Default             |
| -------------------------- | -------------------------------------------------------------------------- | ------------------- |
| `replicaCount`             | Number of registry replicas (> 1 requires an external database)            | `1`                 |
| `image.registry`           | Image registry prefix (overrides `global.imageRegistry`)                   | `""`                |
| `image.repository`         | Registry image repository                                                   | `mcpmesh/registry`  |
| `image.pullPolicy`         | Image pull policy                                                           | `IfNotPresent`      |
| `image.tag`                | Image tag (overrides chart appVersion)                                      | `"3.7"`             |
| `waitForDbImage.registry`  | wait-for-db init image registry prefix (overrides `global.imageRegistry`)  | `""`                |
| `waitForDbImage.repository` | wait-for-db init image repository                                           | `busybox`           |
| `waitForDbImage.tag`       | wait-for-db init image tag                                                  | `"1.35"`            |
| `imagePullSecrets`         | Pull secrets, merged with `global.imagePullSecrets` (deduplicated by name) | `[]`                |
| `nameOverride`             | Override chart name                                                         | `""`                |
| `fullnameOverride`         | Override full name                                                          | `""`                |

`global.imageRegistry` prefixes every image in the chart (the registry image
and the wait-for-db init container) while preserving repository paths — with
`global.imageRegistry=my.registry.internal` the chart pulls
`my.registry.internal/mcpmesh/registry` and `my.registry.internal/busybox`.
Mirror images to the same paths in a private registry.

### Service Configuration

| Parameter             | Description                                                   | Default     |
| --------------------- | ------------------------------------------------------------- | ----------- |
| `service.type`        | Service type                                                  | `ClusterIP` |
| `service.port`        | Service port (targets the container port, `registry.port`)    | `8000`      |
| `service.annotations` | Service annotations                                           | Prometheus scrape annotations |

### Registry Configuration

Each `registry.database.*` connection field inherits `global.postgres.*` when
left unset (the `mcp-mesh-core` umbrella shares one `global.postgres` block
with every datastore consumer); an explicit value here always wins.

With `global.postgres.generatedSecret: true` and no password/existingSecret
configured at either level, the credential is read from the auto-generated
Secret of the umbrella's bundled postgres chart
(`<release>-mcp-mesh-postgres-credentials`, key `password`; name overridable
via `global.postgres.generatedSecretName`) through the regular
existingSecret machinery. An explicit password always wins over the
generated secret. Standalone installs of this chart are unaffected unless
that global is set — when reusing the umbrella values file for a standalone
registry release, set `global.postgres.generatedSecretName` explicitly,
because the default name is derived from the release name.

| Parameter                          | Description                                       | Default               |
| ---------------------------------- | ------------------------------------------------- | --------------------- |
| `registry.host`                    | Registry host address                             | `"0.0.0.0"`           |
| `registry.port`                    | Registry port                                     | `8000`                |
| `registry.database.type`           | `postgres` or `sqlite` (single replica only; the registry has no other driver) | `"postgres"` |
| `registry.database.waitForDatabase` | Run the wait-for-db init container until the database accepts connections (postgres) | `true` |
| `registry.database.host`           | PostgreSQL host                                   | `"mcp-mesh-postgres"` |
| `registry.database.port`           | PostgreSQL port                                   | `5432`                |
| `registry.database.name`           | Database name                                     | `"mcpmesh"`           |
| `registry.database.username`       | Database username                                 | `"mcpmesh"`           |
| `registry.database.password`       | Database password (URL-encoded into the DSN)      | `""`                  |
| `registry.database.sslmode`        | PostgreSQL SSL mode: `disable`, `require`, `verify-ca`, `verify-full` | `"disable"` |
| `registry.database.tls.caSecret`   | Secret with CA cert for `verify-ca`/`verify-full` (mounted, added to DSN as `sslrootcert`) | `""` |
| `registry.database.tls.caKey`      | Key of the CA cert in the secret                  | `"ca.crt"`            |
| `registry.database.existingSecret` | Existing secret with the DB credentials (see modes below)                     | `""` |
| `registry.database.existingSecretUrlKey` | Key in the existing secret holding a complete `postgres://` DSN, consumed directly (no composition, no URL-safety requirement). Empty = password-only mode | `""` |
| `registry.database.existingSecretPasswordKey` | Key in the existing secret holding the password (injected via `$(DATABASE_PASSWORD)`; must be URL-safe) | `"password"` |
| `registry.logging.level`           | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `"DEBUG"`             |
| `registry.logging.debug`           | Debug mode                                        | `"true"`              |
| `registry.performance.timeoutThreshold` | Seconds without a heartbeat before an agent is marked unhealthy | `20` |
| `registry.performance.healthCheckInterval` | Seconds between the registry's agent health sweeps | `10` |
| `registry.observability.exporterType` | Trace exporter: `otlp`, `console` or `json` (see [Autoscaling](#autoscaling)) | `"otlp"` |

### Redis Configuration

`registry.redis.*` is the single source of truth for the registry's Redis
endpoint: session storage and distributed-trace streaming share the derived
`REDIS_URL`. Each connection field inherits `global.redis.*` when left unset
here; an explicit value always wins.

| Parameter                                  | Description                                                              | Default            |
| ------------------------------------------ | ------------------------------------------------------------------------ | ------------------ |
| `registry.redis.enabled`                   | Enable Redis (session storage + trace stream)                            | `true`             |
| `registry.redis.host`                      | Redis host                                                               | See values.yaml    |
| `registry.redis.port`                      | Redis port                                                               | `6379`             |
| `registry.redis.password`                  | AUTH password; moves `REDIS_URL` into the chart secret, URL-encoded      | `""`               |
| `registry.redis.existingSecret`            | Existing secret with the Redis credentials                                | `""` |
| `registry.redis.existingSecretUrlKey`      | Key in the existing secret holding a complete `redis://`/`rediss://` URL, consumed directly (no composition, no URL-safety requirement). Empty = password-only mode | `""` |
| `registry.redis.existingSecretPasswordKey` | Key of the password in the existing secret (injected via `$(REDIS_PASSWORD)`; must be URL-safe) | `"redis-password"` |
| `registry.redis.tls.enabled`               | Use `rediss://` (pair with `serviceTLS.redis.*` for CA/client certs)     | `false`            |

### Persistence

With sqlite the database file lives on the data volume at
`persistence.mountPath`: a PVC when `persistence.enabled`, otherwise an
`emptyDir` that is lost when the pod is replaced. With postgres nothing is
written there.

| Parameter                   | Description        | Default         |
| --------------------------- | ------------------ | --------------- |
| `persistence.enabled`       | Enable persistence | `false`         |
| `persistence.storageClass`  | Storage class name | `""`            |
| `persistence.accessMode`    | Access mode        | `ReadWriteOnce` |
| `persistence.size`          | Volume size        | `10Gi`          |
| `persistence.existingClaim` | Use existing PVC   | `""`            |
| `persistence.mountPath`     | Mount path         | `/data`         |

### Security

| Parameter                               | Description                      | Default   |
| --------------------------------------- | -------------------------------- | --------- |
| `registry.security.tls.enabled`         | Enable TLS                       | `false`   |
| `registry.security.tls.secretName`      | Existing TLS secret              | `""`      |
| `registry.security.tls.mode`            | `off`, `auto` or `strict`; any mode other than `off` requires `registry.security.trust.backend` | `"off"` |
| `registry.security.trust.backend`       | Trust backend(s), comma-separated: `localca`, `filestore`, `k8s-secrets`, `spire` | `""` |
| `registry.security.adminPort`           | Serve `/admin/*` on this separate port instead of the main one (`0` = main port). Plain `http://` with no client-certificate check unless `adminTLS` — restrict it with a NetworkPolicy | `0` |
| `registry.security.adminTLS`            | Serve `adminPort` with the registry's certificate and `tls.mode` client-certificate policy (`MCP_MESH_ADMIN_TLS`). Requires `adminPort`, `tls.enabled` and a `tls.mode` other than `off`. Switches the admin port to `https://`; with `tls.mode=strict` only a cert-capable client gets through, and `meshctl` has none, so `meshctl registry drain` gets 403 | `false` |

### Probes

`startupProbe`, `livenessProbe` and `readinessProbe` are rendered as given and
can be tuned or replaced (for an `exec` handler, also set `httpGet: null`);
`null` restores a probe's default. All three use `GET /health`, which never
consults the database or any dependency.

With `registry.security.tls` on (`tls.enabled` and `tls.mode` `auto` or
`strict`) the main port serves only HTTPS, so an `httpGet` probe without an
explicit `scheme` is rendered with `scheme: HTTPS`. In `strict` mode every
request without a client certificate gets 403, `/health` included, and the
kubelet presents none, so those probes are rendered as `tcpSocket` checks of
the same port instead.

| Parameter                             | Description                    | Default |
| ------------------------------------- | ------------------------------ | ------- |
| `startupProbe.failureThreshold`       | Startup attempts, 10s apart    | `30`    |
| `livenessProbe.initialDelaySeconds`   | Liveness delay                 | `30`    |
| `readinessProbe.initialDelaySeconds`  | Readiness delay                | `10`    |

### Ingress

| Parameter             | Description                 | Default         |
| --------------------- | --------------------------- | --------------- |
| `ingress.enabled`     | Enable ingress              | `false`         |
| `ingress.className`   | Ingress class name          | `""`            |
| `ingress.annotations` | Ingress annotations         | `{}`            |
| `ingress.hosts`       | Ingress hosts configuration | See values.yaml |
| `ingress.tls`         | TLS configuration           | `[]`            |

### Resources

| Parameter                   | Description    | Default |
| --------------------------- | -------------- | ------- |
| `resources.limits.cpu`      | CPU limit      | `500m`  |
| `resources.limits.memory`   | Memory limit   | `512Mi` |
| `resources.requests.cpu`    | CPU request    | `100m`  |
| `resources.requests.memory` | Memory request | `128Mi` |

### Autoscaling

| Parameter                                       | Description               | Default |
| ----------------------------------------------- | ------------------------- | ------- |
| `autoscaling.enabled`                           | Enable HPA                | `false` |
| `autoscaling.minReplicas`                       | Minimum replicas          | `1`     |
| `autoscaling.maxReplicas`                       | Maximum replicas          | `10`    |
| `autoscaling.targetCPUUtilizationPercentage`    | Target CPU utilization    | `80`    |
| `autoscaling.targetMemoryUtilizationPercentage` | Target memory utilization | `80`    |

The registry is stateless when backed by an external database, so the HPA is
safe to enable. Autoscaling (and `replicaCount > 1`) with
`registry.database.type=sqlite` fails at template time: sqlite is a
single-writer local file and cannot be shared across replicas.

Correlation-mode tracing is the one exception to "stateless". The default
exporter (`registry.observability.exporterType: otlp`) is replica-safe: every
replica streams the spans it consumes straight through to Tempo, which
reassembles a trace by its ID however the spans were split on the way in.
Override it to `console` or `json` and each replica instead assembles traces
in its own memory, while Redis hands each `mesh:trace` entry to exactly one
consumer in the shared consumer group — so at N replicas every logical trace
completes as N fragments, and `meshctl trace <id>` answers from whichever
fragment the replica behind the Service holds. Keep the registry at one
replica in those modes, or leave the exporter at `otlp`. The registry warns at
startup whenever correlation mode is active.

### HA Scheduling

| Parameter                       | Description                                                                                                        | Default |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------- |
| `defaultTopologySpread.enabled` | Soft zone + node spread (`ScheduleAnyway`) applied automatically when more than one replica is possible             | `true`  |
| `topologySpreadConstraints`     | Explicit constraints; replace the built-in soft defaults entirely                                                   | `[]`    |
| `podDisruptionBudget.enabled`   | PDB; engages only when more than one replica is guaranteed (`replicaCount > 1` or `autoscaling.minReplicas > 1`)    | `true`  |
| `podDisruptionBudget.minAvailable` | Minimum available pods during voluntary disruptions                                                              | `1`     |

At `replicaCount: 1` (the default) neither the spread constraints nor the PDB
render — a `minAvailable` PDB on a single-replica deployment would block node
drains. Hard placement requirements (`DoNotSchedule`, pod anti-affinity) stay
opt-in via `topologySpreadConstraints` / `affinity`.

### Monitoring

| Parameter                      | Description                          | Default |
| ------------------------------ | ------------------------------------ | ------- |
| `serviceMonitor.enabled`       | Create ServiceMonitor for Prometheus | `false` |
| `serviceMonitor.interval`      | Scrape interval                      | `30s`   |
| `serviceMonitor.scrapeTimeout` | Scrape timeout                       | `10s`   |

## Examples

### Using PostgreSQL Database

```yaml
registry:
  database:
    type: postgres
    host: postgres.database.svc.cluster.local
    port: 5432
    name: mcp_registry
    username: mcp_user
    password: supersecret
```

### Using sqlite (single replica)

```yaml
registry:
  database:
    type: sqlite
persistence:
  enabled: true # keep the database across pod restarts
```

The database file is `<persistence.mountPath>/mcp_mesh_registry.db`
(`/data/mcp_mesh_registry.db` by default, the registry image's own
`DATABASE_URL`). To use a different file, set `DATABASE_URL` in `env`, on a
writable volume — the root filesystem is read-only.

### External Managed Datastores (TLS + auth)

```yaml
registry:
  database:
    type: postgres
    host: mydb.example.com
    port: 5432
    name: mcpmesh
    username: mcp_user
    password: "s3cret!" # URL-encoded automatically
    sslmode: verify-full
    tls:
      caSecret: pg-ca # secret containing the server CA certificate
      caKey: ca.crt
  redis:
    host: myredis.example.com
    port: 6380
    password: "redis-secret" # renders rediss://:<encoded>@host:port into the chart secret
    tls:
      enabled: true
```

With `registry.redis.password` set, `REDIS_URL` is rendered into the chart
secret instead of the configmap. To source Redis credentials from an existing
secret instead, prefer a complete URL — it is consumed directly via
`secretKeyRef`, so the password never needs to be URL-safe:

```yaml
registry:
  redis:
    existingSecret: my-redis-secret
    existingSecretUrlKey: redis-url # key holding rediss://:<password>@host:port
```

If the secret only carries the password, fall back to composition:

```yaml
registry:
  redis:
    host: myredis.example.com
    existingSecret: my-redis-secret
    existingSecretPasswordKey: redis-password
    tls:
      enabled: true
```

Note: in password-only mode the password is injected via Kubernetes
`$(REDIS_PASSWORD)` expansion without URL-encoding, so it must be URL-safe.

### Using Existing Secret for Database

Preferred: store a complete DSN in the secret. It is consumed directly via
`secretKeyRef` — nothing is composed, so the password never needs to be
URL-safe. Encode `sslmode` (and `sslrootcert`, if any) in the DSN itself;
`tls.caSecret` still mounts the CA at `/etc/service-tls/postgres` for the DSN
to reference.

```yaml
registry:
  database:
    type: postgres
    host: mydb.example.com # still drives the wait-for-db init container
    port: 5432
    existingSecret: my-db-secret
    existingSecretUrlKey: database-url # key holding postgres://user:pass@host:5432/db?sslmode=verify-full
```

If the secret only carries the password, fall back to in-pod composition:

```yaml
registry:
  database:
    type: postgres
    host: mydb.example.com
    port: 5432
    name: mcpmesh
    username: mcp_user # username comes from values, only the password from the secret
    existingSecret: my-db-secret
    existingSecretPasswordKey: password
    sslmode: verify-full # sslmode and tls.* apply in this mode too
    tls:
      caSecret: pg-ca
```

In password-only mode `DATABASE_URL` is composed in the pod via Kubernetes
`$(DATABASE_PASSWORD)` expansion from the existing secret, so the password is
never templated into a chart-managed resource. It is not URL-encoded either,
so it must be URL-safe.

### Enabling TLS

```yaml
registry:
  security:
    tls:
      enabled: true
      mode: "strict"
      secretName: my-tls-secret
    trust:
      backend: "k8s-secrets"
```

The registry verifies client certificates in any TLS mode other than `off`
and refuses to start without a trust backend, so the chart fails the render
when `tls.mode` is set and `trust.backend` is empty.

### Production Configuration

This keeps `registry.observability.exporterType` at its `otlp` default, which
is what makes multiple replicas safe for tracing — see
[Autoscaling](#autoscaling). With postgres the registry needs no volume, so
`persistence` stays off. The TLS block assumes a `registry-tls` Secret (for
example from a cert-manager `Certificate`) and entity CAs published as
Secrets labelled for the `k8s-secrets` trust backend; see `meshctl man
security`. With `mode: strict` the probes become `tcpSocket` checks, since the
kubelet cannot present a client certificate (see [Probes](#probes)).

```yaml
resources:
  limits:
    cpu: 2
    memory: 4Gi
  requests:
    cpu: 500m
    memory: 1Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10

podDisruptionBudget:
  enabled: true
  minAvailable: 2

networkPolicy:
  enabled: true

registry:
  database:
    type: postgres
    host: postgres.database.svc.cluster.local
    existingSecret: registry-db
    existingSecretUrlKey: database-url
  security:
    tls:
      enabled: true
      mode: strict
      secretName: registry-tls
    trust:
      backend: k8s-secrets
```

## Upgrading

To upgrade the chart:

```bash
helm upgrade mcp-registry ./helm/mcp-mesh-registry
```

## Troubleshooting

### Registry not starting

Check the pod logs:

```bash
kubectl logs -l app.kubernetes.io/name=mcp-mesh-registry
```

### Database connection issues

Verify database credentials and connectivity:

```bash
kubectl exec -it <pod-name> -- nc -zv <database-host> <database-port>
```

### Persistence issues

Check PVC status:

```bash
kubectl get pvc -l app.kubernetes.io/name=mcp-mesh-registry
```
