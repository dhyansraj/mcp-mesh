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
Names of the Grafana objects referenced in NOTES output: the fullname (used for
the Deployment and the data PVC) and the auto-generated admin Secret. The source
of truth is "mcp-mesh-grafana.secretName" (+ "mcp-mesh-grafana.fullname") in
helm/mcp-mesh-grafana/templates/_helpers.tpl; the umbrella cannot call subchart
helpers, so this reproduces only its RELEASE-NAME branch.

The two therefore drift as soon as the grafana subchart gets a nameOverride /
fullnameOverride: that renames the real Secret while this copy keeps the
literal "mcp-mesh-grafana", and the retrieval command printed in NOTES returns
NotFound. Nothing catches that — unlike postgres, this chart has neither a
guard nor a generatedSecretName escape hatch (only NOTES text is affected, so
no workload breaks). Keep the derivations in sync by hand when either changes.
*/}}
{{- define "mcp-mesh-core.grafanaFullname" -}}
{{- if contains "mcp-mesh-grafana" .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-mcp-mesh-grafana" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{- define "mcp-mesh-core.grafanaSecretName" -}}
{{- printf "%s-secret" (include "mcp-mesh-core.grafanaFullname" .) -}}
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

{{/*
Guard: commonAnnotations must not disable the Namespace's
"helm.sh/resource-policy": keep.

In this umbrella chart commonAnnotations is consumed by exactly one resource —
the Namespace — so setting this key here can only be aimed at that object, and
the only reason to set anything but "keep" is to switch off the protection that
stops `helm uninstall` cascading through every resource in the namespace.
Neither Helm nor Kubernetes would flag it: `helm template` renders the
duplicate key without error and the API server takes last-wins, so the
namespace would silently go back to being garbage-collected. Fail instead.
An explicit "keep" is harmless and stays a silent no-op — namespace.yaml drops
it from the merged map rather than emitting the key twice. Invoked
unconditionally from namespace.yaml.
*/}}
{{- define "mcp-mesh-core.validateNamespaceResourcePolicy" -}}
{{- $policy := dig "helm.sh/resource-policy" "keep" (.Values.commonAnnotations | default dict) | toString -}}
{{- if ne $policy "keep" -}}
{{- fail (printf "commonAnnotations sets \"helm.sh/resource-policy\"=%q, which would override the Namespace's own \"keep\" annotation (last-wins, silently) and put the namespace — and every resource inside it, chart-owned or not — back in `helm uninstall`'s blast radius. Remove the key from commonAnnotations; it is the only resource this chart applies commonAnnotations to, and \"keep\" is already set. To retire the namespace, delete it deliberately with kubectl after uninstalling" $policy) -}}
{{- end -}}
{{- end }}
