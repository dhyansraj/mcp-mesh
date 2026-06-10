{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-postgres.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-postgres.fullname" -}}
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
{{- define "mcp-mesh-postgres.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-postgres.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-postgres.chart" . }}
{{ include "mcp-mesh-postgres.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: database
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-postgres.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-postgres.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Provisioned database / credentials. Precedence per field: explicit
postgres.* > global.postgres.* (the mcp-mesh-core umbrella shares one
global.postgres block, so the bundled database is provisioned with the same
credentials every consumer connects with) > chart default.
*/}}
{{- define "mcp-mesh-postgres.database" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce .Values.postgres.database $g.name "mcpmesh" -}}
{{- end }}

{{- define "mcp-mesh-postgres.username" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce .Values.postgres.username $g.username "mcpmesh" -}}
{{- end }}

{{- define "mcp-mesh-postgres.password" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce .Values.postgres.password $g.password "mcpmesh123" -}}
{{- end }}

{{/*
Reject global.postgres.existingSecret while this bundled chart renders:
provisioning can only use the inline/default password (there is no secret
plumbing here), while every consumer would read its credential from the
external secret — a silent runtime auth failure. This chart only renders
when it is enabled (postgres.enabled in the mcp-mesh-core umbrella), so the
guard fires exactly on the broken combination. Invoked unconditionally from
the statefulset.
*/}}
{{- define "mcp-mesh-postgres.validateCredentialSource" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- if $g.existingSecret -}}
{{- fail "global.postgres.existingSecret cannot be combined with the bundled PostgreSQL chart: provisioning would use the inline/default password while consumers read credentials from the external secret. Disable the bundled subchart (postgres.enabled=false) to use an external database, or drop global.postgres.existingSecret and use inline global.postgres credentials" -}}
{{- end -}}
{{- end }}
