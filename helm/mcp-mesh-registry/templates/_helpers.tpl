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
Effective PostgreSQL connection settings as JSON. Per-field precedence:
explicit registry.database.* > global.postgres.* (shared once by the
mcp-mesh-core umbrella with every datastore consumer) > chart default.
The chart defaults live here — values.yaml ships the inheritable fields
empty so an unset field can fall through to the global. tls.* is flattened
to tlsCaSecret/tlsCaKey for the consumers.
*/}}
{{- define "mcp-mesh-registry.databaseSettings" -}}
{{- $db := .Values.registry.database -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- $dbTls := $db.tls | default dict -}}
{{- $gTls := $g.tls | default dict -}}
{{- dict
      "host" (coalesce $db.host $g.host "mcp-mesh-postgres")
      "port" (coalesce $db.port $g.port 5432 | int)
      "name" (coalesce $db.name $g.name "mcpmesh")
      "username" (coalesce $db.username $g.username "mcpmesh")
      "password" (or $db.password $g.password "")
      "sslmode" (coalesce $db.sslmode $g.sslmode "disable")
      "existingSecret" (or $db.existingSecret $g.existingSecret "")
      "existingSecretUrlKey" (or $db.existingSecretUrlKey $g.existingSecretUrlKey "")
      "existingSecretPasswordKey" (coalesce $db.existingSecretPasswordKey $g.existingSecretPasswordKey "password")
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
Removed-key guard. distributedTracing.redisUrl was dead config — no template
ever consumed it — so honoring it now would silently switch endpoints on
upgrade for values files still carrying it. Fail loudly with migration
guidance instead. Invoked unconditionally from the configmap.
*/}}
{{- define "mcp-mesh-registry.validateNoDeprecatedRedisUrl" -}}
{{- if dig "observability" "distributedTracing" "redisUrl" "" .Values.registry -}}
{{- fail "registry.observability.distributedTracing.redisUrl was never consumed and has been removed; configure registry.redis.{host,port,password,tls} instead — the trace stream shares that endpoint" -}}
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
Get persistence volume claim name
*/}}
{{- define "mcp-mesh-registry.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- include "mcp-mesh-registry.fullname" . }}-data
{{- end }}
{{- end }}
