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

{{/* Same reproduction of the subchart's fullname, same drift caveat, for the
     tempo claim named in NOTES when persistence is opted back in. */}}
{{- define "mcp-mesh-core.tempoFullname" -}}
{{- if contains "mcp-mesh-tempo" .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-mcp-mesh-tempo" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Removed-key guards. These umbrella-level keys were dead config — no template
ever consumed them — so a values file still carrying one would silently
no-op while the user expects effect (a no-op network policy in particular).
Fail loudly with migration guidance instead. Invoked unconditionally from
namespace.yaml. global.coreReleaseName only fails on a value that is neither
the shipped default "mcp-core" (carried harmlessly by copied values files)
nor this release's own name (what a parent umbrella holding core plus the
ingress or agent charts sets, since those charts read it and globals reach
every subchart). Likewise the three `*.enabled` flags only fail when
true: false was their shipped default.
*/}}
{{- define "mcp-mesh-core.validateNoRemovedKeys" -}}
{{- if dig "enabled" false (.Values.networkPolicies | default dict) -}}
{{- fail "networkPolicies.enabled was never consumed and has been removed; enable the per-chart policy instead: mcp-mesh-registry.networkPolicy.enabled (and networkPolicy.enabled on each agent release)" -}}
{{- end -}}
{{- if dig "enabled" false (.Values.serviceMonitors | default dict) -}}
{{- fail "serviceMonitors.enabled was never consumed and has been removed; enable the per-chart monitor instead: mcp-mesh-registry.serviceMonitor.enabled (and serviceMonitor.enabled on each agent release)" -}}
{{- end -}}
{{- if dig "enabled" false (.Values.podDisruptionBudgets | default dict) -}}
{{- fail "podDisruptionBudgets.enabled was never consumed and has been removed; the registry's PodDisruptionBudget is mcp-mesh-registry.podDisruptionBudget, on by default, and engages once mcp-mesh-registry.replicaCount > 1 (or autoscaling.minReplicas > 1)" -}}
{{- end -}}
{{- $coreReleaseName := dig "coreReleaseName" "" (.Values.global | default dict) -}}
{{- /* Equal to this release's name it describes this release, which is the
       umbrella case: a parent chart holding core alongside the ingress or
       agent charts, which read global.coreReleaseName, passes the same
       global down to core. */ -}}
{{- if and $coreReleaseName (ne $coreReleaseName "mcp-core") (ne $coreReleaseName .Release.Name) -}}
{{- fail (printf "global.coreReleaseName=%q names a different release than this one (%q), and this chart does not read it: with a non-default release name, set global.postgres.host, global.redis.host, and the *-mcp-mesh-tempo endpoints to \"<release>-mcp-mesh-<component>\" explicitly. global.coreReleaseName belongs on mcp-mesh-agent and mcp-mesh-ingress releases; inside your own umbrella that holds core, set it to the umbrella's release name" $coreReleaseName .Release.Name) -}}
{{- end -}}
{{- end }}

{{/*
External-database guard. postgres.enabled=false removes the bundled
PostgreSQL, but every consumer still defaults to it: the host is
global.postgres.host ("mcp-core-mcp-mesh-postgres") and, with no password or
existingSecret, the credential is the bundled chart's generated Secret, which
no longer renders. The result used to be a registry stuck forever in its
wait-for-db init container, referencing a Secret that does not exist.

There is no in-memory registry to fall back to: the registry needs a
database, so with the bundled one off an external one must be configured.
Checked for each consumer that is on — the registry (unless it runs sqlite)
and the UI (unless ui.database.url overrides the global block) — against the
same precedence the consumer applies. Invoked unconditionally from
namespace.yaml.
*/}}
{{- define "mcp-mesh-core.validateExternalDatabase" -}}
{{- if not .Values.postgres.enabled -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- $bundled := list (printf "%s-mcp-mesh-postgres" .Release.Name) "mcp-core-mcp-mesh-postgres" -}}
{{- $consumers := list -}}
{{- $reg := index .Values "mcp-mesh-registry" | default dict -}}
{{- $regDb := dig "registry" "database" (dict) $reg | default dict -}}
{{- if and .Values.registry.enabled (ne (toString ($regDb.type | default "postgres")) "sqlite") -}}
{{- /* Full-DSN mode (existingSecret + existingSecretUrlKey, either layer):
       the DSN carries its own host, and registry.database.host only feeds
       the wait-for-db init container. */ -}}
{{- $regDsn := and (or $regDb.existingSecret $g.existingSecret) (or $regDb.existingSecretUrlKey $g.existingSecretUrlKey) -}}
{{- $wait := get $regDb "waitForDatabase" -}}
{{- $waitOn := or (kindIs "invalid" $wait) (ne (lower (toString $wait)) "false") -}}
{{- $consumers = append $consumers (dict
      "name" "the registry"
      "host" (coalesce $regDb.host $g.host "mcp-mesh-postgres")
      "credential" (or $regDb.password $g.password $regDb.existingSecret $g.existingSecret)
      "dsn" $regDsn
      "waitOn" $waitOn) -}}
{{- end -}}
{{- $ui := index .Values "mcp-mesh-ui" | default dict -}}
{{- if and .Values.ui.enabled (not (dig "ui" "database" "url" "" $ui)) -}}
{{- $consumers = append $consumers (dict
      "name" "the UI"
      "host" (coalesce $g.host "mcp-mesh-postgres")
      "credential" (or $g.password $g.existingSecret)
      "dsn" (and $g.existingSecret $g.existingSecretUrlKey)
      "waitOn" false) -}}
{{- end -}}
{{- $fix := "An external PostgreSQL database is required: set global.postgres.host (plus port/name/username) and global.postgres.password or global.postgres.existingSecret — see \"External managed datastores\" in the chart README — or leave postgres.enabled on" -}}
{{- range $consumers -}}
{{- if and .dsn (has .host $bundled) -}}
{{- /* The connection is fine; only the wait-for-db probe would aim at the
       bundled host and never succeed. */ -}}
{{- if .waitOn -}}
{{- fail (printf "postgres.enabled=false turns off the bundled PostgreSQL. Using the full DSN from its existing secret, %s connects fine, but its wait-for-db init container still waits on %s, which no longer exists, so the pod would never start. Set global.postgres.host (or mcp-mesh-registry.registry.database.host) and port to the DSN's host, or set mcp-mesh-registry.registry.database.waitForDatabase=false" .name .host) -}}
{{- end -}}
{{- else if has .host $bundled -}}
{{- fail (printf "postgres.enabled=false turns off the bundled PostgreSQL, but %s still connects to it (%s). %s" .name .host $fix) -}}
{{- end -}}
{{- if and (not .credential) $g.generatedSecret -}}
{{- fail (printf "postgres.enabled=false turns off the bundled PostgreSQL, but %s still takes its password from the bundled chart's generated Secret, which is no longer rendered. %s" .name $fix) -}}
{{- end -}}
{{- end -}}
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
