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
