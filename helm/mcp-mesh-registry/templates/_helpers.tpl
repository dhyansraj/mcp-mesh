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
Validated PostgreSQL sslmode (default disable). Invoked from the configmap for
every non-sqlite database — in addition to both DSN builders below — so an
invalid value fails at template time in all modes.
*/}}
{{- define "mcp-mesh-registry.databaseSSLMode" -}}
{{- $sslmode := .Values.registry.database.sslmode | default "disable" -}}
{{- if not (has $sslmode (list "disable" "require" "verify-ca" "verify-full")) -}}
{{- fail (printf "registry.database.sslmode must be one of: disable, require, verify-ca, verify-full (got %q)" $sslmode) -}}
{{- end -}}
{{- $sslmode -}}
{{- end }}

{{/*
DSN query string: validated sslmode plus sslrootcert when a CA secret is mounted.
*/}}
{{- define "mcp-mesh-registry.databaseURLParams" -}}
{{- $db := .Values.registry.database -}}
{{- $params := printf "?sslmode=%s" (include "mcp-mesh-registry.databaseSSLMode" .) -}}
{{- if dig "tls" "caSecret" "" $db -}}
{{- $params = printf "%s&sslrootcert=/etc/service-tls/postgres/%s" $params (dig "tls" "caKey" "ca.crt" $db) -}}
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
{{- $db := .Values.registry.database -}}
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
username comes from registry.database.username.
*/}}
{{- define "mcp-mesh-registry.composedDatabaseURL" -}}
{{- $db := .Values.registry.database -}}
{{- $user := $db.username | urlquery | replace "+" "%20" -}}
{{- printf "postgres://%s:$(DATABASE_PASSWORD)@%s:%d/%s%s" $user $db.host ($db.port | int) $db.name (include "mcp-mesh-registry.databaseURLParams" .) -}}
{{- end }}

{{/*
Redis scheme: rediss when registry.redis.tls.enabled, redis otherwise.
*/}}
{{- define "mcp-mesh-registry.redisScheme" -}}
{{- if dig "tls" "enabled" false .Values.registry.redis -}}rediss{{- else -}}redis{{- end -}}
{{- end }}

{{/*
Redis URL built from registry.redis.* — the single source of truth for the
registry's Redis endpoint (session storage and trace stream share REDIS_URL).
An inline password is URL-encoded. Not used when an existing secret supplies
the password (the deployment composes the URL via $(REDIS_PASSWORD)) or a
full URL (consumed directly via existingSecretUrlKey).
*/}}
{{- define "mcp-mesh-registry.redisURL" -}}
{{- $redis := .Values.registry.redis -}}
{{- $auth := "" -}}
{{- if $redis.password -}}
{{- $auth = printf ":%s@" ($redis.password | urlquery | replace "+" "%20") -}}
{{- end -}}
{{- printf "%s://%s%s:%v" (include "mcp-mesh-registry.redisScheme" .) $auth $redis.host ($redis.port | default 6379) -}}
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
{{- $redisUrlInSecret := and .Values.registry.redis.enabled .Values.registry.redis.password (not .Values.registry.redis.existingSecret) -}}
{{- if or (and (ne .Values.registry.database.type "sqlite") (not .Values.registry.database.existingSecret)) (and .Values.registry.security.auth.enabled (not .Values.registry.security.auth.existingSecret)) $redisUrlInSecret -}}
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
