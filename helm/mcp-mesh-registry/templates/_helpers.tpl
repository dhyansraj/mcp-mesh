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
Get the database URL
*/}}
{{- define "mcp-mesh-registry.databaseURL" -}}
{{- if eq .Values.registry.database.type "sqlite" }}
{{- printf "sqlite:///%s" .Values.registry.database.path }}
{{- else if eq .Values.registry.database.type "postgres" }}
{{- if .Values.registry.database.existingSecret }}
{{- printf "postgres://$(DATABASE_USERNAME):$(DATABASE_PASSWORD)@%s:%d/%s" .Values.registry.database.host (.Values.registry.database.port | int) .Values.registry.database.name }}
{{- else }}
{{- printf "postgres://%s:%s@%s:%d/%s" .Values.registry.database.username .Values.registry.database.password .Values.registry.database.host (.Values.registry.database.port | int) .Values.registry.database.name }}
{{- end }}
{{- else if eq .Values.registry.database.type "mysql" }}
{{- if .Values.registry.database.existingSecret }}
{{- printf "mysql://$(DATABASE_USERNAME):$(DATABASE_PASSWORD)@%s:%d/%s" .Values.registry.database.host (.Values.registry.database.port | int) .Values.registry.database.name }}
{{- else }}
{{- printf "mysql://%s:%s@%s:%d/%s" .Values.registry.database.username .Values.registry.database.password .Values.registry.database.host (.Values.registry.database.port | int) .Values.registry.database.name }}
{{- end }}
{{- end }}
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
