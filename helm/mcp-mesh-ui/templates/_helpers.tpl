{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-ui.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "mcp-mesh-ui.fullname" -}}
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
Common labels
*/}}
{{- define "mcp-mesh-ui.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-ui.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "mcp-mesh-ui.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-ui.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-ui.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Shared datastore settings (global.postgres / global.redis) as JSON — the
mcp-mesh-core umbrella shares one block with every datastore consumer. The
UI consumes full URLs, so the globals are composed into a DSN/URL here,
mirroring the mcp-mesh-registry chart's composition. Precedence: explicit
ui.database.url / ui.redis.url > global.* > chart default.
*/}}
{{- define "mcp-mesh-ui.globalPostgres" -}}
{{- dig "postgres" (dict) (.Values.global | default dict) | default dict | toJson -}}
{{- end }}

{{- define "mcp-mesh-ui.globalRedis" -}}
{{- dig "redis" (dict) (.Values.global | default dict) | default dict | toJson -}}
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
{{- define "mcp-mesh-ui.generatedPostgresSecretName" -}}
{{- $g := include "mcp-mesh-ui.globalPostgres" . | fromJson -}}
{{- if $g.generatedSecretName -}}
{{- $g.generatedSecretName -}}
{{- else if contains "mcp-mesh-postgres" .Release.Name -}}
{{- printf "%s-credentials" (.Release.Name | trunc 63 | trimSuffix "-") -}}
{{- else -}}
{{- printf "%s-credentials" (printf "%s-mcp-mesh-postgres" .Release.Name | trunc 63 | trimSuffix "-") -}}
{{- end -}}
{{- end }}

{{/*
Existing-secret name for the database credentials: set only when no explicit
ui.database.url overrides the global layer. Non-empty means DATABASE_URL is
consumed via secretKeyRef (urlKey mode) or composed via $(DATABASE_PASSWORD)
(password mode) instead of being rendered into the chart Secret.

With global.postgres.generatedSecret true and no password/existingSecret set
anywhere, the auto-generated Secret of the bundled postgres chart is used
(password-key mode, key "password" — the deployment's passwordKey default).
An explicit global.postgres.password wins over the generated secret.
*/}}
{{- define "mcp-mesh-ui.databaseExistingSecret" -}}
{{- $g := include "mcp-mesh-ui.globalPostgres" . | fromJson -}}
{{- if not .Values.ui.database.url -}}
{{- if $g.existingSecret -}}
{{- $g.existingSecret -}}
{{- else if and ($g.generatedSecret | default false) (not $g.password) -}}
{{- include "mcp-mesh-ui.generatedPostgresSecretName" . -}}
{{- end -}}
{{- end -}}
{{- end }}

{{- define "mcp-mesh-ui.redisExistingSecret" -}}
{{- $g := include "mcp-mesh-ui.globalRedis" . | fromJson -}}
{{- if not .Values.ui.redis.url -}}{{- $g.existingSecret | default "" -}}{{- end -}}
{{- end }}

{{/*
Validated PostgreSQL sslmode from global.postgres (default disable).
*/}}
{{- define "mcp-mesh-ui.databaseSSLMode" -}}
{{- $g := include "mcp-mesh-ui.globalPostgres" . | fromJson -}}
{{- $sslmode := $g.sslmode | default "disable" -}}
{{- if not (has $sslmode (list "disable" "require" "verify-ca" "verify-full")) -}}
{{- fail (printf "global.postgres.sslmode must be one of: disable, require, verify-ca, verify-full (got %q)" $sslmode) -}}
{{- end -}}
{{- $sslmode -}}
{{- end }}

{{/*
DSN query string: validated sslmode plus sslrootcert when global.postgres
supplies a CA secret (mounted at /etc/service-tls/postgres).
*/}}
{{- define "mcp-mesh-ui.databaseURLParams" -}}
{{- $g := include "mcp-mesh-ui.globalPostgres" . | fromJson -}}
{{- $gTls := $g.tls | default dict -}}
{{- $params := printf "?sslmode=%s" (include "mcp-mesh-ui.databaseSSLMode" .) -}}
{{- if $gTls.caSecret -}}
{{- $params = printf "%s&sslrootcert=/etc/service-tls/postgres/%s" $params ($gTls.caKey | default "ca.crt") -}}
{{- end -}}
{{- $params -}}
{{- end }}

{{/*
Effective DATABASE_URL for the chart Secret. Not used when an existing
secret supplies the credential (see databaseExistingSecret above).
Registry semantics: any global connection part (host, port, name, username,
password) composes a DSN with the remaining parts coalesced to their
defaults — a password without a host still applies over the default host.
The credential-less readonly placeholder renders only when no global part is
set at all: it carries no password, so it cannot authenticate anywhere — the
UI fails fast at startup with a clear database error instead of shipping a
guessable default. Configure ui.database.url (ideally a read-only role) or
global.postgres.* for a working deployment.
*/}}
{{- define "mcp-mesh-ui.databaseURL" -}}
{{- if .Values.ui.database.url -}}
{{- .Values.ui.database.url -}}
{{- else -}}
{{- $g := include "mcp-mesh-ui.globalPostgres" . | fromJson -}}
{{- if or $g.host $g.port $g.name $g.username $g.password -}}
{{- $user := ($g.username | default "mcpmesh") | urlquery | replace "+" "%20" -}}
{{- $pass := ($g.password | default "") | urlquery | replace "+" "%20" -}}
{{- printf "postgresql://%s:%s@%s:%d/%s%s" $user $pass (coalesce $g.host "mcp-mesh-postgres") (coalesce $g.port 5432 | int) ($g.name | default "mcpmesh") (include "mcp-mesh-ui.databaseURLParams" .) -}}
{{- else -}}
{{- "postgresql://mcp_mesh_readonly@mcp-mesh-postgres:5432/mcpmesh?sslmode=disable" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
DATABASE_URL for the global.postgres.existingSecret password-only mode: the
password is supplied at runtime via $(DATABASE_PASSWORD) expansion (the
secretKeyRef env must be rendered before this one). It is not URL-encoded
in this mode and must be URL-safe.
*/}}
{{- define "mcp-mesh-ui.composedDatabaseURL" -}}
{{- $g := include "mcp-mesh-ui.globalPostgres" . | fromJson -}}
{{- $user := ($g.username | default "mcpmesh") | urlquery | replace "+" "%20" -}}
{{- printf "postgresql://%s:$(DATABASE_PASSWORD)@%s:%d/%s%s" $user ($g.host | default "mcp-mesh-postgres") (coalesce $g.port 5432 | int) ($g.name | default "mcpmesh") (include "mcp-mesh-ui.databaseURLParams" .) -}}
{{- end }}

{{/*
Redis scheme: rediss when global.redis.tls.enabled, redis otherwise.
*/}}
{{- define "mcp-mesh-ui.redisScheme" -}}
{{- $g := include "mcp-mesh-ui.globalRedis" . | fromJson -}}
{{- if dig "tls" "enabled" false $g -}}rediss{{- else -}}redis{{- end -}}
{{- end }}

{{/*
Effective REDIS_URL for the chart Secret. An inline global password is
URL-encoded and applies over the coalesced default host (registry
semantics), so a password without a host still renders a credentialed URL.
Not used when an existing secret supplies the credential.
*/}}
{{- define "mcp-mesh-ui.redisURL" -}}
{{- if .Values.ui.redis.url -}}
{{- .Values.ui.redis.url -}}
{{- else -}}
{{- $g := include "mcp-mesh-ui.globalRedis" . | fromJson -}}
{{- $auth := "" -}}
{{- if $g.password -}}
{{- $auth = printf ":%s@" ($g.password | urlquery | replace "+" "%20") -}}
{{- end -}}
{{- printf "%s://%s%s:%d" (include "mcp-mesh-ui.redisScheme" .) $auth (coalesce $g.host "mcp-mesh-redis") (coalesce $g.port 6379 | int) -}}
{{- end -}}
{{- end }}

{{/*
REDIS_URL for the global.redis.existingSecret password-only mode: composed
via $(REDIS_PASSWORD) expansion, so the password must be URL-safe.
*/}}
{{- define "mcp-mesh-ui.composedRedisURL" -}}
{{- $g := include "mcp-mesh-ui.globalRedis" . | fromJson -}}
{{- printf "%s://:$(REDIS_PASSWORD)@%s:%d" (include "mcp-mesh-ui.redisScheme" .) ($g.host | default "mcp-mesh-redis") (coalesce $g.port 6379 | int) -}}
{{- end }}

{{/*
Whether the chart-managed Secret renders. Shared by secret.yaml and the
deployment's checksum/secret annotation and envFrom secretRef, so neither
references a non-rendered manifest. False only when BOTH URLs come from
existing secrets.
*/}}
{{- define "mcp-mesh-ui.secretEnabled" -}}
{{- if or (not (include "mcp-mesh-ui.databaseExistingSecret" .)) (not (include "mcp-mesh-ui.redisExistingSecret" .)) -}}
true
{{- end -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
*/}}
{{- define "mcp-mesh-ui.image" -}}
{{- $img := .Values.image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag | default .Chart.AppVersion -}}
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
{{- define "mcp-mesh-ui.imagePullSecrets" -}}
{{- $names := list -}}
{{- $global := dig "imagePullSecrets" (list) (.Values.global | default dict) -}}
{{- range concat ($global | default list) ((.Values.imagePullSecrets) | default list) -}}
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
