{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-agent.fullname" -}}
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
{{- define "mcp-mesh-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-agent.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-agent.chart" . }}
{{ include "mcp-mesh-agent.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: agent
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "mcp-mesh-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mcp-mesh-agent.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the secret name
*/}}
{{- define "mcp-mesh-agent.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- include "mcp-mesh-agent.fullname" . }}-secret
{{- end }}
{{- end }}

{{/*
Get agent name
*/}}
{{- define "mcp-mesh-agent.agentName" -}}
{{- if .Values.agent.name }}
{{- .Values.agent.name }}
{{- else }}
{{- include "mcp-mesh-agent.fullname" . }}
{{- end }}
{{- end }}

{{/*
Build capabilities JSON
*/}}
{{- define "mcp-mesh-agent.capabilities" -}}
{{- if .Values.agent.capabilities }}
{{- .Values.agent.capabilities | toJson }}
{{- else }}
[]
{{- end }}
{{- end }}

{{/*
Build dependencies JSON
*/}}
{{- define "mcp-mesh-agent.dependencies" -}}
{{- if .Values.agent.dependencies }}
{{- .Values.agent.dependencies | toJson }}
{{- else }}
[]
{{- end }}
{{- end }}

{{/*
Detect if using Python runtime (checks agent.runtime first, then image name)
*/}}
{{- define "mcp-mesh-agent.isPython" -}}
{{- if eq (toString .Values.agent.runtime) "python" }}true
{{- else if and (not .Values.agent.runtime) (contains "python" .Values.image.repository) }}true
{{- end }}
{{- end }}

{{/*
Shared Redis settings (global.redis) as JSON — the same shape the
mcp-mesh-core umbrella shares with its datastore consumers. This chart is
standalone (not an umbrella subchart), so set the same global.redis values
on each agent release (e.g. reuse the umbrella's datastore values file).
Precedence: explicit agent.observability.distributedTracing.redisUrl >
global.redis.* > chart default.
*/}}
{{- define "mcp-mesh-agent.globalRedis" -}}
{{- dig "redis" (dict) (.Values.global | default dict) | default dict | toJson -}}
{{- end }}

{{/*
Redis scheme: rediss when global.redis.tls.enabled, redis otherwise.
*/}}
{{- define "mcp-mesh-agent.redisScheme" -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- if dig "tls" "enabled" false $g -}}rediss{{- else -}}redis{{- end -}}
{{- end }}

{{/*
Where REDIS_URL is sourced from:
  - "configmap": plain URL in the chart configmap (no credential involved —
    explicit redisUrl, composed global host without password, or the default)
  - "secret": inline global.redis.password — the URL carries a credential, so
    it renders into the chart Secret and is consumed via secretKeyRef
  - "existing-url" / "existing-password": global.redis.existingSecret modes,
    consumed via secretKeyRef in the deployment
*/}}
{{- define "mcp-mesh-agent.redisURLSource" -}}
{{- $explicit := dig "observability" "distributedTracing" "redisUrl" "" .Values.agent -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- if $explicit -}}
configmap
{{- else if $g.existingSecret -}}
{{- if $g.existingSecretUrlKey -}}existing-url{{- else -}}existing-password{{- end -}}
{{- else if $g.password -}}
secret
{{- else -}}
configmap
{{- end -}}
{{- end }}

{{/*
Effective REDIS_URL (trace publishing). An inline global password is
URL-encoded and applies over the coalesced default host (registry
semantics), so a password without a host still renders a credentialed URL —
redisURLSource classifies that combination as "secret" and the Secret must
carry the credential. Not used in the existing-secret modes.
*/}}
{{- define "mcp-mesh-agent.redisURL" -}}
{{- $explicit := dig "observability" "distributedTracing" "redisUrl" "" .Values.agent -}}
{{- if $explicit -}}
{{- $explicit -}}
{{- else -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- $auth := "" -}}
{{- if $g.password -}}
{{- $auth = printf ":%s@" ($g.password | urlquery | replace "+" "%20") -}}
{{- end -}}
{{- printf "%s://%s%s:%d" (include "mcp-mesh-agent.redisScheme" .) $auth (coalesce $g.host "mcp-core-mcp-mesh-redis") (coalesce $g.port 6379 | int) -}}
{{- end -}}
{{- end }}

{{/*
REDIS_URL for the global.redis.existingSecret password-only mode: composed
via $(REDIS_PASSWORD) expansion, so the password must be URL-safe.
*/}}
{{- define "mcp-mesh-agent.composedRedisURL" -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- printf "%s://:$(REDIS_PASSWORD)@%s:%d" (include "mcp-mesh-agent.redisScheme" .) ($g.host | default "mcp-core-mcp-mesh-redis") (coalesce $g.port 6379 | int) -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
*/}}
{{- define "mcp-mesh-agent.image" -}}
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
{{- define "mcp-mesh-agent.imagePullSecrets" -}}
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
