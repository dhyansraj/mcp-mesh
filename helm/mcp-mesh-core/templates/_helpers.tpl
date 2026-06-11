{{/*
Name of the auto-generated PostgreSQL credentials Secret, for NOTES output.
The umbrella cannot call subchart helpers, so this inlines the same
derivation: the source of truth is "mcp-mesh-postgres.credentialsSecretName"
(+ "mcp-mesh-postgres.fullname") in helm/mcp-mesh-postgres/templates/
_helpers.tpl — "<fullname>-credentials" with the standard fullname rules
(release name containing the chart name is used as-is; otherwise
"<release>-<chart>"; both truncated to 63 chars). Keep them in sync.
global.postgres.generatedSecretName overrides; the subchart guards against
nameOverride/fullnameOverride desyncing this default derivation.
*/}}
{{- define "mcp-mesh-core.postgresCredentialsSecretName" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- if $g.generatedSecretName -}}
{{- $g.generatedSecretName -}}
{{- else if contains "mcp-mesh-postgres" .Release.Name -}}
{{- printf "%s-credentials" (.Release.Name | trunc 63 | trimSuffix "-") -}}
{{- else -}}
{{- printf "%s-credentials" (printf "%s-mcp-mesh-postgres" .Release.Name | trunc 63 | trimSuffix "-") -}}
{{- end -}}
{{- end }}

{{/*
Name of the auto-generated Grafana admin Secret, for NOTES output. Source of
truth: "<fullname>-secret" in helm/mcp-mesh-grafana/templates/secret.yaml
(+ "mcp-mesh-grafana.fullname" in that chart's _helpers.tpl). Keep in sync.
*/}}
{{- define "mcp-mesh-core.grafanaSecretName" -}}
{{- if contains "mcp-mesh-grafana" .Release.Name -}}
{{- printf "%s-secret" (.Release.Name | trunc 63 | trimSuffix "-") -}}
{{- else -}}
{{- printf "%s-secret" (printf "%s-mcp-mesh-grafana" .Release.Name | trunc 63 | trimSuffix "-") -}}
{{- end -}}
{{- end }}
