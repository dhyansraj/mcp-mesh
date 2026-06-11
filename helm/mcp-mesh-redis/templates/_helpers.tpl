{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-redis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-redis.fullname" -}}
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
{{- define "mcp-mesh-redis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-redis.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-redis.chart" . }}
{{ include "mcp-mesh-redis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: cache
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-redis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-redis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Reject global.redis credentials while this bundled chart renders: this chart
starts redis-server without AUTH (no requirepass plumbing), so a
global.redis.password / global.redis.existingSecret credential renders into
every consumer's REDIS_URL but the bundled server would reject (or ignore)
it — a silent runtime auth failure. This chart only renders when it is
enabled (redis.enabled in the mcp-mesh-core umbrella), so the guard fires
exactly on the broken combination. Invoked unconditionally from the
deployment.
*/}}
{{- define "mcp-mesh-redis.validateCredentialSource" -}}
{{- $g := dig "redis" (dict) (.Values.global | default dict) | default dict -}}
{{- if or $g.password $g.existingSecret -}}
{{- fail "global.redis.password / global.redis.existingSecret cannot be combined with the bundled Redis chart: it runs without AUTH, so the credential every consumer connects with can never work. Disable the bundled subchart (redis.enabled=false) and point global.redis at an external Redis, or drop the global.redis credentials" -}}
{{- end -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
The tag is upstream-versioned (no .Chart.AppVersion fallback — that tracks a
different versioning line), so an empty tag can only come from an explicit
override; fail loudly at template time instead of rendering an invalid ref.
*/}}
{{- define "mcp-mesh-redis.image" -}}
{{- $img := .Values.image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag -}}
{{- if not $tag -}}
{{- fail "image.tag must not be empty; set the upstream image tag explicitly" -}}
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
{{- define "mcp-mesh-redis.imagePullSecrets" -}}
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
