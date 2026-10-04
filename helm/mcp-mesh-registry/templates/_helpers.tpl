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

The only consumed keys under distributedTracing are 'enabled' and
'retention' (rendered as MCP_MESH_DISTRIBUTED_TRACING_ENABLED and
MCP_MESH_TRACE_RETENTION); both are allowlisted below.

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
- security.tls.existingSecret: the README documented this name but every
  template reads security.tls.secretName; a carried value would mount an
  empty secret name. Renamed — fail naming the consumed key.
- security.tls.certFile/keyFile: never consumed; the cert and key paths are
  fixed (/etc/tls/<certKey|keyKey>). Shipped as "" in the old values.yaml,
  so empty is tolerated; only a non-empty value fails.
- createNamespace: unlike the rest of this list this key WAS consumed, by a
  templates/namespace.yaml that rendered a release-owned Namespace. It was
  never declared in values.yaml and never documented, so it only ever fired
  for someone who set it deliberately. The template is gone — an owned
  Namespace makes `helm uninstall` cascade to every resource in it — so a
  carried value would now silently no-op. Only a truthy value fails;
  createNamespace: false is a no-op either way.
- security.auth.*: the registry has no token (or any other credential)
  authentication. These keys mounted an AUTH_TOKENS variable nothing reads,
  so enabling them left the registry exactly as open as before while
  looking protected. Registry access control is mTLS: security.tls plus a
  trust backend. The shipped defaults (enabled: false, type: token,
  tokens: [], existingSecret: "", secretKey: tokens) are tolerated; any
  other value fails.
- workloadType, service.targetPort, registry.logging.format,
  registry.healthCheck.*, registry.performance.{maxConnections,
  connectionTimeout,requestTimeout}, podMonitor.*: declared in values.yaml
  from v1.0.0 to v3.7.x with the same defaults, never read by any template.
  Each looked like it configured something (a StatefulSet, the container
  port, the log format, health checking, connection limits, a PodMonitor),
  so a changed value fails naming the key that does that job, if any. The
  shipped defaults are tolerated, via removedKeyGuard.
- registry.database.path: shipped as "/data/registry.db" and documented as
  the sqlite file, but never rendered — every sqlite install ran on the
  image's own DATABASE_URL, /data/mcp_mesh_registry.db. Honouring it now
  would point an existing install at a new, empty database (losing jobs and
  events without an error), so a changed value fails instead, naming where
  the data actually is. "" and the shipped value pass.
- registry.database.existingSecretUsernameKey: removed in #1190 as a plain
  drop. The username always came from registry.database.username, never
  from the secret, so a carried non-default key would quietly connect as
  the wrong user. The shipped "username" is tolerated.
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
{{- if or (eq $key "enabled") (eq $key "retention") -}}
{{- else if not (hasKey $oldTracingDefaults $key) -}}
{{- fail (printf "registry.observability.distributedTracing.%s was never consumed and has been removed; only 'enabled' and 'retention' live under distributedTracing (telemetryEndpoint and exporterType sit directly under registry.observability). Stream tuning is set via the top-level env list: TRACE_BATCH_SIZE, TRACE_TIMEOUT, TRACE_PRETTY_OUTPUT, TRACE_ENABLE_STATS, TELEMETRY_PROTOCOL" $key) -}}
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
{{- $tls := (dig "security" "tls" (dict) .Values.registry) | default dict -}}
{{- if get $tls "existingSecret" -}}
{{- fail (printf "registry.security.tls.existingSecret was never consumed and has been renamed; the templates read registry.security.tls.secretName — set secretName: %q instead (mounted read-only at /etc/tls)" (toString (get $tls "existingSecret"))) -}}
{{- end -}}
{{- range $key := list "certFile" "keyFile" -}}
{{- if get $tls $key -}}
{{- fail (printf "registry.security.tls.%s was never consumed and has been removed (set to %q, so it would silently no-op); the cert and key are mounted from registry.security.tls.secretName at /etc/tls/<certKey|keyKey>" $key (toString (get $tls $key))) -}}
{{- end -}}
{{- end -}}
{{- $oldAuthDefaults := dict "enabled" "false" "type" "token" "tokens" "[]" "existingSecret" "" "secretKey" "tokens" -}}
{{- range $key, $val := (dig "security" "auth" (dict) .Values.registry) | default dict -}}
{{- /* nil (a carried `existingSecret: ~` / `tokens: ~`) is empty, not intent. */ -}}
{{- if not (kindIs "invalid" $val) -}}
{{- $got := kindIs "slice" $val | ternary (toJson $val) (toString $val) -}}
{{- if or (not (hasKey $oldAuthDefaults $key)) (ne $got (get $oldAuthDefaults $key)) -}}
{{- fail (printf "registry.security.auth.%s has been removed: the registry has no token authentication, so these keys protected nothing (they mounted an AUTH_TOKENS variable that is never read). Secure the registry with mTLS instead: set registry.security.tls.enabled=true with registry.security.tls.secretName, registry.security.tls.mode=strict, and registry.security.trust.backend, then remove registry.security.auth from your values" $key) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $removed := list
      (dict "path" "workloadType" "value" .Values.workloadType "shipped" "Deployment"
            "hint" "The registry always renders a Deployment; it is stateless when backed by postgres")
      (dict "path" "service.targetPort" "value" (dig "targetPort" nil (.Values.service | default dict)) "shipped" 8000
            "hint" "The Service always targets the container's named port \"http\"; change registry.port to move the listener")
      (dict "path" "registry.logging.format" "value" (dig "logging" "format" nil .Values.registry) "shipped" "json"
            "hint" "The registry has no log-format setting")
      (dict "path" "registry.healthCheck" "value" (dig "healthCheck" nil .Values.registry) "shipped" (dict "enabled" true "interval" 30 "timeout" 10)
            "hint" "Probe timing for the registry pod is livenessProbe / readinessProbe / startupProbe; agent heartbeat tracking is registry.performance.timeoutThreshold and healthCheckInterval")
      (dict "path" "registry.performance.maxConnections" "value" (dig "performance" "maxConnections" nil .Values.registry) "shipped" 1000
            "hint" "Database pool sizes are the DB_MAX_OPEN_CONNECTIONS / DB_MAX_IDLE_CONNECTIONS env vars, settable via the top-level env list")
      (dict "path" "registry.performance.connectionTimeout" "value" (dig "performance" "connectionTimeout" nil .Values.registry) "shipped" 30
            "hint" "The database connection timeout is the DB_CONNECTION_TIMEOUT env var, settable via the top-level env list")
      (dict "path" "registry.performance.requestTimeout" "value" (dig "performance" "requestTimeout" nil .Values.registry) "shipped" 60
            "hint" "The registry has no request-timeout setting")
      (dict "path" "podMonitor" "value" .Values.podMonitor "shipped" (dict "enabled" false "namespace" "" "interval" "30s" "scrapeTimeout" "10s" "labels" (dict) "honorLabels" true "metricRelabelings" (list) "relabelings" (list))
            "hint" "This chart renders no PodMonitor; use serviceMonitor.enabled")
      (dict "path" "registry.database.path" "value" (dig "database" "path" nil .Values.registry | default nil) "shipped" "/data/registry.db"
            "what" "was never applied and has been removed"
            "hint" (printf "Every sqlite install has run on the registry image's own DATABASE_URL, so the data lives at %s. To use a different file, set DATABASE_URL in the top-level env list (env: [{name: DATABASE_URL, value: <path on a writable volume>}])" (include "mcp-mesh-registry.sqliteDefaultPath" .)))
      (dict "path" "registry.database.existingSecretUsernameKey" "value" (dig "database" "existingSecretUsernameKey" nil .Values.registry) "shipped" "username"
            "hint" "The username always comes from registry.database.username (or global.postgres.username), never from the secret; set it there, or use existingSecretUrlKey with a full DSN that carries the username") -}}
{{- range $removed -}}
{{- include "mcp-mesh-registry.removedKeyGuard" . -}}
{{- end -}}
{{- if .Values.createNamespace -}}
{{- fail "createNamespace has been removed; it rendered a release-owned Namespace, which makes `helm uninstall` delete the namespace and cascade to every resource in it. Create the namespace out of band instead: `helm install --create-namespace` or Argo CD's `syncOptions: CreateNamespace=true` — neither ties the namespace to the release" -}}
{{- end -}}
{{- end }}

{{/*
Fail on a removed values key whose value diverges from what the chart used to
ship. Call with (dict "path" <dotted key> "value" <user value> "shipped" <old
default> "hint" <where the job lives now>), plus an optional "what" replacing
"was never read by any template and has been removed". nil and the old default carry no
intent and pass; a map recurses key by key, so a copied block passes while one
changed field fails naming itself. Scalars compare as strings (30 and "30" are
the same carried value); lists compare as JSON.
*/}}
{{- define "mcp-mesh-registry.removedKeyGuard" -}}
{{- $v := .value -}}
{{- if kindIs "invalid" $v -}}
{{- else if and (kindIs "map" $v) (kindIs "map" .shipped) -}}
{{- range $k, $sub := $v -}}
{{- include "mcp-mesh-registry.removedKeyGuard" (dict "path" (printf "%s.%s" $.path $k) "value" $sub "shipped" (get $.shipped $k) "hint" $.hint "what" $.what) -}}
{{- end -}}
{{- else -}}
{{- $got := ternary (toJson $v) (toString $v) (or (kindIs "slice" $v) (kindIs "map" $v)) -}}
{{- $want := ternary (toJson .shipped) (toString .shipped) (or (kindIs "slice" .shipped) (kindIs "map" .shipped)) -}}
{{- if ne $got $want -}}
{{- fail (printf "%s %s (set to %s, so it would silently do nothing). %s. Remove %s from your values" .path (.what | default "was never read by any template and has been removed") $got .hint .path) -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
A registry probe spec. Call with (dict "name" "livenessProbe" "root" $).
Renders the value of .Values.<name>, except in the two cases where that value
is not something the user chose:

- Absent (or null): `helm upgrade --reuse-values` from chart <= 3.7 reuses the
  OLD chart's values, which have no startupProbe — before #1574 the probes
  were hard-coded in deployment.yaml and values.yaml declared only liveness
  and readiness, which nothing read. The built-in default renders instead,
  so the probe does not silently disappear on upgrade.
- The old shipped livenessProbe: it said initialDelaySeconds 10 while the
  hard-coded probe was 30. A copied or reused copy of it is treated as unset,
  so it does not cut the liveness delay on upgrade.

A partial value is deep-merged over the default (see below).

A probe cannot be removed: Helm merges values maps over the defaults, so the
only way to drop a key is null, and null is indistinguishable from the
absent key above. (Before #1574 they could not be changed at all.) The
defaults below must match values.yaml; scripts/check_helm_render_matrix.py
pins both.
*/}}
{{- define "mcp-mesh-registry.probe" -}}
{{- $health := dict "path" "/health" "port" "http" -}}
{{- $defaults := dict
      "startupProbe" (dict "httpGet" $health "initialDelaySeconds" 5 "periodSeconds" 10 "timeoutSeconds" 5 "failureThreshold" 30)
      "livenessProbe" (dict "httpGet" $health "initialDelaySeconds" 30 "periodSeconds" 10 "timeoutSeconds" 5 "failureThreshold" 3)
      "readinessProbe" (dict "httpGet" $health "initialDelaySeconds" 10 "periodSeconds" 5 "timeoutSeconds" 3 "failureThreshold" 3) -}}
{{- $oldShippedLiveness := dict "httpGet" $health "initialDelaySeconds" 10 "periodSeconds" 10 "timeoutSeconds" 5 "failureThreshold" 3 -}}
{{- $default := get $defaults .name -}}
{{- $v := index .root.Values .name -}}
{{- if or (kindIs "invalid" $v) (and (eq .name "livenessProbe") (eq (toJson $v) (toJson $oldShippedLiveness))) -}}
{{- $v = $default -}}
{{- end -}}
{{- /* Deep-merge over the default so a partial value keeps the rest — with
       --reuse-values from 3.7 the startupProbe has no defaults to merge
       with, and `--set startupProbe.failureThreshold=60` alone would render
       a probe with no handler. A value bringing its own handler (exec,
       tcpSocket, grpc) replaces the default httpGet rather than joining it. */}}
{{- $base := deepCopy $default -}}
{{- range $h := list "exec" "tcpSocket" "grpc" -}}
{{- if hasKey $v $h -}}{{- $base = omit $base "httpGet" -}}{{- end -}}
{{- end -}}
{{- $probe := mergeOverwrite $base (deepCopy $v) -}}
{{- /* With TLS on, the main port speaks only HTTPS (runWithTLS), so a plain
       httpGet is answered 400 and the probe fails: an httpGet that names no
       scheme gets HTTPS (the kubelet does not verify the certificate). In
       strict mode TLSVerifyMiddleware answers every certless request 403,
       /health included, and the kubelet presents no client certificate, so
       no httpGet can pass there: such a probe becomes a tcpSocket check of
       the same port. A scheme set explicitly is left alone. */ -}}
{{- $tls := .root.Values.registry.security.tls | default dict -}}
{{- $mode := toString ($tls.mode | default "") -}}
{{- $httpGet := get $probe "httpGet" -}}
{{- if and $tls.enabled $mode (ne $mode "off") (kindIs "map" $httpGet) (not (hasKey $httpGet "scheme")) -}}
{{- if eq $mode "strict" -}}
{{- $probe = set (omit $probe "httpGet") "tcpSocket" (dict "port" ($httpGet.port | default "http")) -}}
{{- else -}}
{{- $_ := set $httpGet "scheme" "HTTPS" -}}
{{- end -}}
{{- end -}}
{{- toYaml $probe -}}
{{- end }}

{{/*
Database type guard. The registry binary has two drivers and picks one from
DATABASE_URL itself: a postgres:// (or postgresql://) DSN, or anything else as
a sqlite file path. There is no MySQL driver, so type: mysql used to render
no DATABASE_URL at all and the registry silently ran on the image's sqlite
file instead. Invoked unconditionally from the configmap.
*/}}
{{- define "mcp-mesh-registry.validateDatabaseType" -}}
{{- $type := toString .Values.registry.database.type -}}
{{- if not (has $type (list "postgres" "sqlite")) -}}
{{- fail (printf "registry.database.type=%q is not supported: the registry has two database drivers, postgres and sqlite. For an external database use registry.database.type=postgres with registry.database.host/name/username and credentials" $type) -}}
{{- end -}}
{{- end }}

{{/*
The sqlite file the registry uses: <persistence.mountPath>/mcp_mesh_registry.db.
The registry image sets DATABASE_URL=/data/mcp_mesh_registry.db, so with the
default mountPath (/data) that is simply the image's own file.
*/}}
{{- define "mcp-mesh-registry.sqliteDefaultPath" -}}
{{- printf "%s/mcp_mesh_registry.db" (.Values.persistence.mountPath | default "/data" | trimSuffix "/") -}}
{{- end }}

{{/*
DATABASE_URL to render for sqlite, or nothing. The binary takes a plain file
path for sqlite, not a sqlite:// URL.

With mountPath /data (the default) nothing is rendered: the image's own
DATABASE_URL already names the file on the data volume, which is how every
sqlite install has run, and a DATABASE_URL the user supplies through env or
envFrom stays in charge. Only a different mountPath needs one — the image's
/data path is then on the read-only root filesystem, so those installs
crash-looped and hold no data to lose. Skipped when the env list already
sets DATABASE_URL, so the container never declares the name twice, and
whenever envFrom is set: the chart cannot see inside a referenced
ConfigMap/Secret, and an env entry would silently override a DATABASE_URL it
supplies. With envFrom and a moved volume, set DATABASE_URL yourself.
*/}}
{{- define "mcp-mesh-registry.sqliteDatabaseURL" -}}
{{- if ne (.Values.persistence.mountPath | default "/data" | trimSuffix "/") "/data" -}}
{{- $userSet := false -}}
{{- range .Values.env | default list -}}
{{- if and (kindIs "map" .) (eq (toString (get . "name")) "DATABASE_URL") -}}{{- $userSet = true -}}{{- end -}}
{{- end -}}
{{- if and (not $userSet) (not .Values.envFrom) -}}{{- include "mcp-mesh-registry.sqliteDefaultPath" . -}}{{- end -}}
{{- end -}}
{{- end }}

{{/*
Whether registry.security.adminTLS is on. Off unless explicitly true (or the
string "true"), so the quoted "false" — truthy in an `if` — stays off.
*/}}
{{- define "mcp-mesh-registry.adminTLS" -}}
{{- $v := dig "security" "adminTLS" nil .Values.registry -}}
{{- if and (not (kindIs "invalid" $v)) (eq (lower (toString $v)) "true") -}}true{{- end -}}
{{- end }}

{{/*
adminTLS guard: the switch only affects a separate admin listener, and only
does anything when the registry itself serves TLS. Without adminPort the
admin endpoints are on the main port, which already uses the registry's
TLS; without tls.enabled the registry logs that the admin port stays
plaintext. Both would leave a user who set adminTLS with an unhardened
admin API, so fail instead. The registry serves TLS only with a tls.mode
other than off as well as a certificate (tlsEnabled() in
src/core/registry/server.go), and mode defaults to off, so that is checked
too. Invoked unconditionally from the configmap.
*/}}
{{- define "mcp-mesh-registry.validateAdminTLS" -}}
{{- if include "mcp-mesh-registry.adminTLS" . -}}
{{- if le (int .Values.registry.security.adminPort) 0 -}}
{{- fail "registry.security.adminTLS applies only to a separate admin listener: set registry.security.adminPort too. Without it the admin endpoints are served on the main port, which already uses the registry's TLS settings" -}}
{{- end -}}
{{- if not .Values.registry.security.tls.enabled -}}
{{- fail "registry.security.adminTLS serves the admin port with the registry's own certificate, so it requires registry.security.tls.enabled=true (with tls.secretName, tls.mode and trust.backend). Without it the admin port stays plain http://" -}}
{{- end -}}
{{- $mode := toString (dig "security" "tls" "mode" "" .Values.registry) -}}
{{- if or (not $mode) (eq $mode "off") -}}
{{- fail (printf "registry.security.adminTLS needs registry.security.tls.mode auto or strict (got %q): the registry serves TLS only when the mode is not off, so the admin port would stay plain http://" $mode) -}}
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
{{- if or (and (ne .Values.registry.database.type "sqlite") (not $db.existingSecret)) $redisUrlInSecret -}}
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
Trust backend guard (issue #1600): the registry refuses to start when
MCP_MESH_TLS_MODE is anything other than off and MCP_MESH_TRUST_BACKEND is
empty, because a chain with no backends would reject every presented
certificate while auto mode still admitted certless clients. Fail at
template time instead of deploying a crash-looping pod. Invoked
unconditionally from the configmap, which renders both variables.
*/}}
{{- define "mcp-mesh-registry.validateTrustBackend" -}}
{{- $mode := toString (dig "security" "tls" "mode" "" .Values.registry) -}}
{{- $backend := trim (toString (dig "security" "trust" "backend" "" .Values.registry)) -}}
{{- if and $mode (ne $mode "off") (not $backend) -}}
{{- fail (printf "registry.security.tls.mode=%s requires registry.security.trust.backend: the registry verifies client certificates in any TLS mode other than off and refuses to start without a trust backend. Set registry.security.trust.backend to one or more of localca, filestore, k8s-secrets, spire (comma-separated), or set registry.security.tls.mode=off" $mode) -}}
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

{{/*
Name of the registry data volume — deliberately not a constant.

Kubernetes merges spec.template.spec.volumes by name, so a stable name whose
type flips between persistentVolumeClaim and emptyDir can end up carrying BOTH
under server-side apply, when the two field sets have different owners; the API
server then rejects the object with "may not specify more than 1 volume type"
and the Deployment sticks unsyncable (#1461). Encoding the type in the key turns
a persistence.enabled toggle into a remove-item + add-item on distinct keys,
which is always representable, in either direction, under Helm, Argo,
client-side and server-side apply alike.

The persistent branch keeps the historical name so installations that never
disabled persistence see no change at all.

The matching volumeMounts entry MUST use this same helper — that list is keyed
by name too, and a mount naming a volume that no longer exists is its own
invalid-Deployment failure.
*/}}
{{- define "mcp-mesh-registry.dataVolumeName" -}}
{{- if .Values.persistence.enabled -}}data{{- else -}}data-ephemeral{{- end -}}
{{- end }}
