{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-registry.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-registry.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "mcp-mesh-registry.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-registry.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-registry.chart" . }}
{{ include "mcp-mesh-registry.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-registry.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-registry.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: registry
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "mcp-mesh-registry.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mcp-mesh-registry.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the auto-generated PostgreSQL credentials Secret created by the
bundled mcp-mesh-postgres chart (global.postgres.generatedSecret mode).
global.postgres.generatedSecretName overrides; the default mirrors the
mcp-mesh-postgres chart's "<fullname>-credentials" — sibling subcharts in
the mcp-mesh-core umbrella share .Release.Name, so both sides derive the
same name. If the postgres subchart uses nameOverride/fullnameOverride, set
global.postgres.generatedSecretName explicitly.
*/}}
{{- define "mcp-mesh-registry.generatedPostgresSecretName" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- if $g.generatedSecretName -}}
{{- $g.generatedSecretName -}}
{{- else if contains "mcp-mesh-postgres" .Release.Name -}}
{{- printf "%s-credentials" (.Release.Name | trunc 63 | trimSuffix "-") -}}
{{- else -}}
{{- printf "%s-credentials" (printf "%s-mcp-mesh-postgres" .Release.Name | trunc 63 | trimSuffix "-") -}}
{{- end -}}
{{- end }}

{{/*
Effective PostgreSQL connection settings as JSON. Per-field precedence:
explicit registry.database.* > global.postgres.* (shared once by the
mcp-mesh-core umbrella with every datastore consumer) > chart default.
The chart defaults live here — values.yaml ships the inheritable fields
empty so an unset field can fall through to the global. tls.* is flattened
to tlsCaSecret/tlsCaKey for the consumers.

When no password and no existing secret are configured anywhere and
global.postgres.generatedSecret is true, the credential comes from the
auto-generated Secret of the bundled postgres chart, consumed through the
regular existingSecret machinery (password-key mode, key "password" — the
generated password is alphanumeric, hence URL-safe for composition).
An explicit password at either level always wins over the generated secret.
*/}}
{{- define "mcp-mesh-registry.databaseSettings" -}}
{{- $db := .Values.registry.database -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- $dbTls := $db.tls | default dict -}}
{{- $gTls := $g.tls | default dict -}}
{{- $password := or $db.password $g.password "" -}}
{{- $existingSecret := or $db.existingSecret $g.existingSecret "" -}}
{{- $urlKey := or $db.existingSecretUrlKey $g.existingSecretUrlKey "" -}}
{{- $passwordKey := coalesce $db.existingSecretPasswordKey $g.existingSecretPasswordKey "password" -}}
{{- if and (not $existingSecret) (not $password) ($g.generatedSecret | default false) -}}
{{- $existingSecret = include "mcp-mesh-registry.generatedPostgresSecretName" . -}}
{{- /* The generated secret only carries a bare "password" key — a stray
       urlKey or passwordKey (set without its existingSecret) must not select
       DSN mode or a key that does not exist in the generated secret. */ -}}
{{- $urlKey = "" -}}
{{- $passwordKey = "password" -}}
{{- end -}}
{{- dict
      "host" (coalesce $db.host $g.host "mcp-mesh-postgres")
      "port" (coalesce $db.port $g.port 5432 | int)
      "name" (coalesce $db.name $g.name "mcpmesh")
      "username" (coalesce $db.username $g.username "mcpmesh")
      "password" $password
      "sslmode" (coalesce $db.sslmode $g.sslmode "disable")
      "existingSecret" $existingSecret
      "existingSecretUrlKey" $urlKey
      "existingSecretPasswordKey" $passwordKey
      "tlsCaSecret" (or $dbTls.caSecret $gTls.caSecret "")
      "tlsCaKey" (coalesce $dbTls.caKey $gTls.caKey "ca.crt")
    | toJson -}}
{{- end }}

{{/*
Effective Redis connection settings as JSON. Per-field precedence: explicit
registry.redis.* > global.redis.* > chart default (same scheme as
databaseSettings above). tls.enabled is a boolean, so presence — not
truthiness — decides which layer wins (hasKey), flattened to tlsEnabled.
*/}}
{{- define "mcp-mesh-registry.redisSettings" -}}
{{- $redis := .Values.registry.redis -}}
{{- $g := dig "redis" (dict) (.Values.global | default dict) | default dict -}}
{{- $rTls := $redis.tls | default dict -}}
{{- $gTls := $g.tls | default dict -}}
{{- $tlsEnabled := false -}}
{{- if hasKey $rTls "enabled" -}}
{{- $tlsEnabled = $rTls.enabled -}}
{{- else if hasKey $gTls "enabled" -}}
{{- $tlsEnabled = $gTls.enabled -}}
{{- end -}}
{{- dict
      "host" (coalesce $redis.host $g.host "mcp-core-mcp-mesh-redis")
      "port" (coalesce $redis.port $g.port 6379 | int)
      "password" (or $redis.password $g.password "")
      "existingSecret" (or $redis.existingSecret $g.existingSecret "")
      "existingSecretUrlKey" (or $redis.existingSecretUrlKey $g.existingSecretUrlKey "")
      "existingSecretPasswordKey" (coalesce $redis.existingSecretPasswordKey $g.existingSecretPasswordKey "redis-password")
      "tlsEnabled" $tlsEnabled
    | toJson -}}
{{- end }}

{{/*
Validated PostgreSQL sslmode (default disable). Invoked from the configmap for
every non-sqlite database — in addition to both DSN builders below — so an
invalid value fails at template time in all modes.
*/}}
{{- define "mcp-mesh-registry.databaseSSLMode" -}}
{{- $sslmode := (include "mcp-mesh-registry.databaseSettings" . | fromJson).sslmode -}}
{{- if not (has $sslmode (list "disable" "require" "verify-ca" "verify-full")) -}}
{{- fail (printf "registry.database.sslmode / global.postgres.sslmode must be one of: disable, require, verify-ca, verify-full (got %q)" $sslmode) -}}
{{- end -}}
{{- $sslmode -}}
{{- end }}

{{/*
DSN query string: validated sslmode plus sslrootcert when a CA secret is mounted.
*/}}
{{- define "mcp-mesh-registry.databaseURLParams" -}}
{{- $db := include "mcp-mesh-registry.databaseSettings" . | fromJson -}}
{{- $params := printf "?sslmode=%s" (include "mcp-mesh-registry.databaseSSLMode" .) -}}
{{- if $db.tlsCaSecret -}}
{{- $params = printf "%s&sslrootcert=/etc/service-tls/postgres/%s" $params $db.tlsCaKey -}}
{{- end -}}
{{- $params -}}
{{- end }}

{{/*
PostgreSQL DSN with URL-encoded credentials, sslmode, and optional CA cert.
The DSN is the only SSL-mode consumer: the registry binary reads DATABASE_URL.
Rendered into the chart Secret. Not used with database.existingSecret (the
deployment composes the DSN via $(DATABASE_PASSWORD) instead).
*/}}
{{- define "mcp-mesh-registry.databaseURL" -}}
{{- $db := include "mcp-mesh-registry.databaseSettings" . | fromJson -}}
{{- $user := $db.username | urlquery | replace "+" "%20" -}}
{{- $pass := $db.password | urlquery | replace "+" "%20" -}}
{{- printf "postgres://%s:%s@%s:%d/%s%s" $user $pass $db.host ($db.port | int) $db.name (include "mcp-mesh-registry.databaseURLParams" .) -}}
{{- end }}

{{/*
PostgreSQL DSN for the database.existingSecret password-only mode (fallback
when no existingSecretUrlKey is set — with a urlKey the deployment consumes
the full DSN from the secret directly and nothing is composed): the password
is supplied at runtime via Kubernetes $(DATABASE_PASSWORD) expansion (the
secretKeyRef env must be rendered before this one), so it is never templated.
The password is not URL-encoded in this mode and must be URL-safe. The
username comes from registry.database.username (or global.postgres.username).
*/}}
{{- define "mcp-mesh-registry.composedDatabaseURL" -}}
{{- $db := include "mcp-mesh-registry.databaseSettings" . | fromJson -}}
{{- $user := $db.username | urlquery | replace "+" "%20" -}}
{{- printf "postgres://%s:$(DATABASE_PASSWORD)@%s:%d/%s%s" $user $db.host ($db.port | int) $db.name (include "mcp-mesh-registry.databaseURLParams" .) -}}
{{- end }}

{{/*
Redis scheme: rediss when registry.redis.tls.enabled (or the inherited
global.redis.tls.enabled), redis otherwise.
*/}}
{{- define "mcp-mesh-registry.redisScheme" -}}
{{- if (include "mcp-mesh-registry.redisSettings" . | fromJson).tlsEnabled -}}rediss{{- else -}}redis{{- end -}}
{{- end }}

{{/*
Redis URL built from the effective redis settings — the single source of
truth for the registry's Redis endpoint (session storage and trace stream
share REDIS_URL). An inline password is URL-encoded. Not used when an
existing secret supplies the password (the deployment composes the URL via
$(REDIS_PASSWORD)) or a full URL (consumed directly via existingSecretUrlKey).
*/}}
{{- define "mcp-mesh-registry.redisURL" -}}
{{- $redis := include "mcp-mesh-registry.redisSettings" . | fromJson -}}
{{- $auth := "" -}}
{{- if $redis.password -}}
{{- $auth = printf ":%s@" ($redis.password | urlquery | replace "+" "%20") -}}
{{- end -}}
{{- printf "%s://%s%s:%d" (include "mcp-mesh-registry.redisScheme" .) $auth $redis.host ($redis.port | int) -}}
{{- end }}

{{/*
Removed-key guards. These keys were dead config — no template ever consumed
them — so a values file carrying one would silently no-op while the user
expects effect. Fail loudly with migration guidance instead. Invoked
unconditionally from the configmap.

Carve-out: the v2.4.0 mcp-mesh-core umbrella SHIPPED these keys as defaults
(nine distributedTracing.* keys including redisUrl, and a 17-entry
registry.environment map — see `git show v2.4.0:helm/mcp-mesh-core/values.yaml`).
A values file copied from it carries them without any user intent, so a key
whose value exactly matches the old shipped default is tolerated; only a
DIVERGING value — user intent that would silently no-op — fails.
- distributedTracing.redisUrl: removed in favor of the shared registry.redis
  endpoint (honoring a divergent value now would silently switch endpoints
  on upgrade; the old default matches the derived default endpoint).
- distributedTracing.* stream keys (streamName, consumerGroup, batchSize,
  ...): never rendered into env; the binary reads TRACE_* env vars, settable
  via the env list.
- registry.environment: never rendered; use the top-level env list.
*/}}
{{- define "mcp-mesh-registry.validateNoRemovedKeys" -}}
{{/* Old shipped defaults, verbatim from the v2.4.0 umbrella values.yaml. */}}
{{- $oldTracingDefaults := dict
      "redisUrl" "redis://mcp-core-mcp-mesh-redis:6379"
      "exporterType" "otlp"
      "telemetryProtocol" "grpc"
      "batchSize" "100"
      "timeout" "5m"
      "prettyOutput" "false"
      "enableStats" "true"
      "streamName" "mesh:trace"
      "consumerGroup" "mcp-mesh-registry-processors" -}}
{{- range $key, $val := (dig "observability" "distributedTracing" (dict) .Values.registry) | default dict -}}
{{- if eq $key "enabled" -}}
{{- else if not (hasKey $oldTracingDefaults $key) -}}
{{- fail (printf "registry.observability.distributedTracing.%s was never consumed and has been removed; only 'enabled' lives under distributedTracing (telemetryEndpoint and exporterType sit directly under registry.observability). Stream tuning is set via the top-level env list: TRACE_BATCH_SIZE, TRACE_TIMEOUT, TRACE_PRETTY_OUTPUT, TRACE_ENABLE_STATS, TELEMETRY_PROTOCOL" $key) -}}
{{- else if ne (toString $val) (get $oldTracingDefaults $key) -}}
{{- if eq $key "redisUrl" -}}
{{- fail (printf "registry.observability.distributedTracing.redisUrl was never consumed and has been removed (set to %q, diverging from the old shipped default, so it would silently no-op); configure registry.redis.{host,port,password,tls} instead — the trace stream shares that endpoint" (toString $val)) -}}
{{- else -}}
{{- fail (printf "registry.observability.distributedTracing.%s was never consumed and has been removed (set to %q, diverging from the old shipped default %q, so it would silently no-op). Stream tuning is set via the top-level env list: TRACE_BATCH_SIZE, TRACE_TIMEOUT, TRACE_PRETTY_OUTPUT, TRACE_ENABLE_STATS, TELEMETRY_PROTOCOL" $key (toString $val) (get $oldTracingDefaults $key)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{/* Old shipped 17-entry registry.environment, verbatim from the v2.4.0
     umbrella values.yaml. */}}
{{- $oldEnvironmentDefaults := dict
      "MCP_MESH_DISTRIBUTED_TRACING_ENABLED" "true"
      "TRACE_EXPORTER_TYPE" "otlp"
      "TELEMETRY_PROTOCOL" "grpc"
      "TRACE_BATCH_SIZE" "100"
      "TRACE_TIMEOUT" "5m"
      "TRACE_PRETTY_OUTPUT" "false"
      "TRACE_ENABLE_STATS" "true"
      "STREAM_NAME" "mesh:trace"
      "CONSUMER_GROUP" "mcp-mesh-registry-processors"
      "MCP_MESH_TRACE_DEBUG" "true"
      "ENABLE_RESPONSE_CACHE" "true"
      "ENABLE_CORS" "true"
      "ENABLE_METRICS" "true"
      "ENABLE_PROMETHEUS" "true"
      "ENABLE_EVENTS" "true"
      "ACCESS_LOG" "true"
      "CACHE_TTL" "30" -}}
{{- range $key, $val := (dig "environment" (dict) .Values.registry) | default dict -}}
{{- if not (hasKey $oldEnvironmentDefaults $key) -}}
{{- fail (printf "registry.environment was never consumed and has been removed (entry %s is not in the old shipped defaults, so it would silently no-op); add environment variables via the top-level env list (name/value entries) instead. Registry TLS/trust settings belong under registry.security" $key) -}}
{{- else if ne (toString $val) (get $oldEnvironmentDefaults $key) -}}
{{- fail (printf "registry.environment was never consumed and has been removed (%s=%q diverges from the old shipped default %q, so it would silently no-op); add environment variables via the top-level env list (name/value entries) instead" $key (toString $val) (get $oldEnvironmentDefaults $key)) -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Whether the chart-managed Secret renders. Shared by secret.yaml and the
deployment's checksum/secret annotation so the checksum never hashes a
non-rendered manifest.
*/}}
{{- define "mcp-mesh-registry.secretEnabled" -}}
{{- $db := include "mcp-mesh-registry.databaseSettings" . | fromJson -}}
{{- $redis := include "mcp-mesh-registry.redisSettings" . | fromJson -}}
{{- $redisUrlInSecret := and .Values.registry.redis.enabled $redis.password (not $redis.existingSecret) -}}
{{- if or (and (ne .Values.registry.database.type "sqlite") (not $db.existingSecret)) (and .Values.registry.security.auth.enabled (not .Values.registry.security.auth.existingSecret)) $redisUrlInSecret -}}
true
{{- end -}}
{{- end }}

{{/*
Render an image reference as [registry/]repository:tag from an image block.
The registry prefix resolves as <block>.registry > global.imageRegistry > ""
(implicit Docker Hub). Repository paths are preserved: with
global.imageRegistry=my.registry.internal this renders
my.registry.internal/mcpmesh/registry and (for the init container)
my.registry.internal/busybox — mirror images to the same paths.
Call with (dict "image" <imageBlock> "root" $) plus an optional
"defaultTag" used when <imageBlock>.tag is empty. Only the chart's own
image may fall back to Chart.AppVersion — that version is meaningless for
third-party images like the busybox init container, so without a
defaultTag an empty tag fails the render instead.
*/}}
{{- define "mcp-mesh-registry.imageRef" -}}
{{- $img := .image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.root.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag | default (.defaultTag | default "") -}}
{{- if not $tag -}}
{{- fail (printf "image tag for %s must not be empty" $img.repository) -}}
{{- end -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $img.repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}
{{- end }}

{{/*
imagePullSecrets for the pod spec: global.imagePullSecrets merged with the
chart's own imagePullSecrets, deduplicated by name. Entries may be maps
({name: ...}, the Kubernetes shape) or bare strings. Renders nothing when
both lists are empty.
*/}}
{{- define "mcp-mesh-registry.imagePullSecrets" -}}
{{- $names := list -}}
{{- $global := dig "imagePullSecrets" (list) (.Values.global | default dict) -}}
{{- range concat ($global | default list) (.Values.imagePullSecrets | default list) -}}
{{- $name := . -}}
{{- if kindIs "map" . -}}{{- $name = get . "name" -}}{{- end -}}
{{- if and $name (not (has $name $names)) -}}
{{- $names = append $names $name -}}
{{- end -}}
{{- end -}}
{{- if $names -}}
imagePullSecrets:
{{- range $names }}
  - name: {{ . }}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Multi-replica safety guard: sqlite is a single-writer local file — each
replica would either get its own divergent database (emptyDir) or fight
over one ReadWriteOnce volume. Fail at template time instead of deploying
a broken topology. Invoked unconditionally from the deployment.
*/}}
{{- define "mcp-mesh-registry.validateMultiReplica" -}}
{{- if eq .Values.registry.database.type "sqlite" -}}
{{- if .Values.autoscaling.enabled -}}
{{- fail "autoscaling.enabled requires an external database: sqlite is a single-writer local file and cannot be shared across replicas. Set registry.database.type=postgres, or disable autoscaling." -}}
{{- end -}}
{{- if gt (int .Values.replicaCount) 1 -}}
{{- fail "replicaCount > 1 requires an external database: sqlite is a single-writer local file and cannot be shared across replicas. Set registry.database.type=postgres, or keep replicaCount=1." -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Whether more than one registry replica is possible: replicaCount > 1, or the
HPA owns the replica count and can scale beyond one. Gates the default
topology spread constraints.
*/}}
{{- define "mcp-mesh-registry.multiReplica" -}}
{{- if .Values.autoscaling.enabled -}}
{{- if gt (int .Values.autoscaling.maxReplicas) 1 -}}true{{- end -}}
{{- else if gt (int .Values.replicaCount) 1 -}}true{{- end -}}
{{- end }}

{{/*
Whether the PodDisruptionBudget renders. Enabled by default, but it only
engages when the registry is guaranteed more than one replica
(replicaCount > 1, or autoscaling.minReplicas > 1 with the HPA enabled):
a minAvailable PDB on a single-replica deployment blocks node drains.
*/}}
{{- define "mcp-mesh-registry.pdbEnabled" -}}
{{- if .Values.podDisruptionBudget.enabled -}}
{{- if .Values.autoscaling.enabled -}}
{{- if gt (int .Values.autoscaling.minReplicas) 1 -}}true{{- end -}}
{{- else if gt (int .Values.replicaCount) 1 -}}true{{- end -}}
{{- end -}}
{{- end }}

{{/*
Get persistence volume claim name
*/}}
{{- define "mcp-mesh-registry.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- include "mcp-mesh-registry.fullname" . }}-data
{{- end }}
{{- end }}
