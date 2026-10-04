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
Backend Service name for a core component. Call with
(dict "component" "registry" "root" $). core.<component>.service wins when
set (rendered with tpl when it contains "{{"); empty derives
"<global.coreReleaseName>-mcp-mesh-<component>", the Service the
mcp-mesh-core release of that name creates.

Carve-out: the chart used to ship "{{ .Release.Name }}-mcp-mesh-<component>",
which names the INGRESS release, never the core one — two releases in one
namespace cannot share a name, so that default never resolved to a Service.
A carried copy of it is treated as unset.
*/}}
{{- define "mcp-mesh-ingress.coreService" -}}
{{- $root := .root -}}
{{- $service := toString (dig "service" "" (index ($root.Values.core | default dict) .component | default dict)) -}}
{{- $oldDefault := printf "{{ .Release.Name }}-mcp-mesh-%s" .component -}}
{{- if or (not $service) (eq $service $oldDefault) -}}
{{- $core := dig "coreReleaseName" "" ($root.Values.global | default dict) | default "mcp-core" -}}
{{- $chart := printf "mcp-mesh-%s" .component -}}
{{- /* The component chart's fullname rule: a release name that already
       contains the chart name is used as-is. */ -}}
{{- ternary $core (printf "%s-%s" $core $chart) (contains $chart $core) | trunc 63 | trimSuffix "-" -}}
{{- else if contains "{{" $service -}}
{{- tpl $service $root -}}
{{- else -}}
{{- $service -}}
{{- end -}}
{{- end }}

{{/*
The enabled agents list as JSON, each entry completed with its defaults:
service "<name>-mcp-mesh-agent" (the mcp-mesh-agent chart's fullname for a
release called <name>), port 8080 (its service.port), host <name>, path
"/<name>(/|$)(.*)". name is required.
*/}}
{{- define "mcp-mesh-ingress.agents" -}}
{{- $out := list -}}
{{- range $i, $a := .Values.agents | default list -}}
{{- if not $a.name -}}
{{- fail (printf "agents[%d] needs a name: the agent's mcp-mesh-agent release name, from which its Service, host and path are derived" $i) -}}
{{- end -}}
{{- if or (not (hasKey $a "enabled")) (kindIs "invalid" $a.enabled) (ne (lower (toString $a.enabled)) "false") -}}
{{- $service := toString ($a.service | default "") -}}
{{- if contains "{{" $service -}}
{{- $service = tpl $service $ -}}
{{- else if not $service -}}
{{- $service = ternary $a.name (printf "%s-mcp-mesh-agent" $a.name) (contains "mcp-mesh-agent" $a.name) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- $out = append $out (dict
      "name" $a.name
      "service" $service
      "port" ($a.port | default 8080 | int)
      "host" ($a.host | default $a.name)
      "path" ($a.path | default (printf "/%s(/|$)(.*)" $a.name))) -}}
{{- end -}}
{{- end -}}
{{- $out | toJson -}}
{{- end }}

{{/*
Generate common annotations for ingress
*/}}
{{- define "mcp-mesh-ingress.annotations" -}}
{{- with .Values.commonAnnotations }}
{{- toYaml . }}
{{- end }}
{{- if and .Values.tls.mtls .Values.tls.mtls.passthrough }}
nginx.ingress.kubernetes.io/ssl-passthrough: "true"
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
{{- include "mcp-mesh-ingress.validateNoRemovedKeys" . }}
{{- end }}

{{/*
Removed-key guards.
- global.serviceNamespace rendered backends as
  "<service>.<namespace>.svc.cluster.local". An Ingress backend must name a
  Service in the Ingress's own namespace, and the API server rejects a name
  with dots, so any value broke the install. Install this chart into the
  services' namespace instead.
- resources, nodeSelector, tolerations, affinity: this chart renders only
  Ingress and NetworkPolicy objects — no pods — so these never applied to
  anything, the ingress controller included. Shipped empty; a non-empty
  value fails.
*/}}
{{- define "mcp-mesh-ingress.validateNoRemovedKeys" -}}
{{- with dig "serviceNamespace" "" (.Values.global | default dict) -}}
{{- fail (printf "global.serviceNamespace has been removed (set to %q): an Ingress can only route to Services in its own namespace, so install this chart with -n %s instead" (toString .) (toString .)) -}}
{{- end -}}
{{- range $key := list "resources" "nodeSelector" "tolerations" "affinity" -}}
{{- if index $.Values $key -}}
{{- fail (printf "%s was never read by any template and has been removed: this chart renders only Ingress and NetworkPolicy objects, no pods, so it never applied to anything (the ingress controller included). Configure the controller through its own chart" $key) -}}
{{- end -}}
{{- end -}}
{{- end }}
