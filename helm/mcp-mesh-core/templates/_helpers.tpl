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

{{/*
Removed-key guards. These umbrella-level keys were dead config — no template
ever consumed them — so a values file still carrying one would silently
no-op while the user expects effect (a no-op network policy in particular).
Fail loudly with migration guidance instead. Invoked unconditionally from
namespace.yaml. global.coreReleaseName only fails on a non-default value:
the default "mcp-core" was shipped in values.yaml and is carried harmlessly
by copied values files.
*/}}
{{- define "mcp-mesh-core.validateNoRemovedKeys" -}}
{{- if dig "enabled" false (.Values.networkPolicies | default dict) -}}
{{- fail "networkPolicies.enabled was never consumed and has been removed; enable the per-chart policy instead: mcp-mesh-registry.networkPolicy.enabled (and networkPolicy.enabled on each agent release)" -}}
{{- end -}}
{{- if dig "enabled" false (.Values.serviceMonitors | default dict) -}}
{{- fail "serviceMonitors.enabled was never consumed and has been removed; enable the per-chart monitor instead: mcp-mesh-registry.serviceMonitor.enabled (or podMonitor.enabled)" -}}
{{- end -}}
{{- $coreReleaseName := dig "coreReleaseName" "" (.Values.global | default dict) -}}
{{- if and $coreReleaseName (ne $coreReleaseName "mcp-core") -}}
{{- fail "global.coreReleaseName was documentation-only here and has been removed; with a non-default release name, set global.postgres.host, global.redis.host, and the *-mcp-mesh-tempo endpoints to \"<release>-mcp-mesh-<component>\" explicitly (agent releases still use global.coreReleaseName on the mcp-mesh-agent chart)" -}}
{{- end -}}
{{- end }}
