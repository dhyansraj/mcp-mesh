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
