{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-ingress.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-ingress.fullname" -}}
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
{{- define "mcp-mesh-ingress.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-ingress.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-ingress.chart" . }}
{{ include "mcp-mesh-ingress.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: ingress
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-ingress.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-ingress.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Generate full hostname for a service
*/}}
{{- define "mcp-mesh-ingress.hostname" -}}
{{- $host := .host -}}
{{- $domain := .domain -}}
{{- printf "%s.%s" $host $domain }}
{{- end }}

{{/*
Generate service name with namespace support
Expects: dict "service" <string> "serviceNamespace" <string> "root" <context>
*/}}
{{- define "mcp-mesh-ingress.serviceName" -}}
{{- $service := .service -}}
{{- if contains "{{" .service -}}
{{- $service = tpl .service .root -}}
{{- end -}}
{{- if .serviceNamespace }}
{{- printf "%s.%s.svc.cluster.local" $service .serviceNamespace }}
{{- else }}
{{- $service }}
{{- end }}
{{- end }}

{{/*
Generate common annotations for ingress
*/}}
{{- define "mcp-mesh-ingress.annotations" -}}
{{- with .Values.commonAnnotations }}
{{- toYaml . }}
{{- end }}
{{- end }}

{{/*
Generate TLS configuration
*/}}
{{- define "mcp-mesh-ingress.tls" -}}
{{- if .Values.tls.enabled }}
tls:
{{- range .Values.tls.certificates }}
  - hosts:
    {{- range .hosts }}
    - {{ . | quote }}
    {{- end }}
    secretName: {{ .secretName }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Validate ingress configuration
*/}}
{{- define "mcp-mesh-ingress.validate" -}}
{{- if and (not .Values.patterns.hostBased.enabled) (not .Values.patterns.pathBased.enabled) }}
{{- fail "At least one ingress pattern (hostBased or pathBased) must be enabled" }}
{{- end }}
{{- end }}
