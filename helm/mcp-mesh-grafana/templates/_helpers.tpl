{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-grafana.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "mcp-mesh-grafana.fullname" -}}
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
{{- define "mcp-mesh-grafana.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-grafana.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-grafana.chart" . }}
{{ include "mcp-mesh-grafana.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: mcp-mesh
app.kubernetes.io/component: observability
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-grafana.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-grafana.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name of the chart-managed Secret holding the admin password (explicit
grafana.config.adminPassword or the auto-generated one, key: admin-password).
Consumed by secret.yaml, the Deployment's secretKeyRef, and this chart's
NOTES. The mcp-mesh-core umbrella cannot call subchart helpers and reproduces
the release-name branch of this name in "mcp-mesh-core.grafanaSecretName" —
see the caveat there; it does not follow nameOverride/fullnameOverride.
*/}}
{{- define "mcp-mesh-grafana.secretName" -}}
{{- printf "%s-secret" (include "mcp-mesh-grafana.fullname" .) -}}
{{- end }}

{{/*
Guard for grafana.config.generatedSecret=false. That flag is enforced HERE and
nowhere else: secret.yaml never reads it, so with an explicit adminPassword the
chart-managed Secret still renders (it must — the Deployment references it) and
the value is stable per render either way. What the flag buys is refusing the
one non-deterministic case: no credential at all, where secret.yaml would
invent a random password (lookup returns nothing without a cluster, so every
GitOps render rotates it). Turning that into a render-time error is the
GitOps-safe posture. Failing here rather than emitting nothing also avoids a
Deployment referencing a Secret that never exists (CreateContainerConfigError
at pod start, no template error). Invoked unconditionally from the deployment.

--set-string yields the STRING "false", which is truthy in a template `if` —
compare stringified so both spellings disable generation.
*/}}
{{- define "mcp-mesh-grafana.validateCredentialSource" -}}
{{- $cfg := .Values.grafana.config | default dict -}}
{{- $disabled := has (lower (printf "%v" (dig "generatedSecret" true $cfg))) (list "false" "0" "off" "no") -}}
{{- if and $disabled (not $cfg.adminPassword) (not $cfg.existingSecret) -}}
{{- fail "grafana.config.generatedSecret=false requires grafana.config.adminPassword or grafana.config.existingSecret: with generation disabled nothing creates the admin-password Secret, and Grafana's Deployment would reference one that does not exist. Set a credential (existingSecret keeps the password out of your values), or re-enable generatedSecret" -}}
{{- end -}}
{{- end }}

{{/*
Whether the bundled dashboards render at all. Two conditions, not one: the
operator has to want them (grafana.dashboards.enabled) AND the dashboard JSON
has to be present.

files/dashboards/ is gitignored and populated by the dashboard-sync step in
helm-release.yml, so it is in every released tarball and absent from every
source checkout. The mount used to be conditional on the flag alone while the
ConfigMap holding the dashboard was also conditional on the file — so from a
clone the volume referenced a ConfigMap that never rendered and the kubelet
blocked the pod indefinitely, naming the missing ConfigMap rather than the
missing file. A mount may not be less conditional than the object backing it.

Everything dashboard-shaped keys off this single helper: the dashboard
ConfigMap, the provisioning-provider ConfigMap (a file provider pointing at a
directory that does not exist is a startup error for Grafana, so leaving it
behind would trade one broken pod for another), grafana.ini's
default_home_dashboard_path, and both volume/volumeMount pairs.

Released charts are unaffected — the JSON is present, so this is true exactly
when grafana.dashboards.enabled is.
*/}}
{{- define "mcp-mesh-grafana.dashboardsEnabled" -}}
{{- if and .Values.grafana.dashboards.enabled (.Files.Get "files/dashboards/mcp-mesh-overview.json") -}}
true
{{- end -}}
{{- end }}

{{/*
Removed-key guard, same convention as mcp-mesh-registry.validateNoRemovedKeys:
a key no template ever consumed is deleted rather than left to no-op silently,
and a values file still carrying it fails with migration guidance instead.
Invoked unconditionally from the deployment.

- grafana.dashboards.configMaps: read by nothing. It listed a ConfigMap name
  ("mcp-mesh-dashboards") that no volume, no mount and no provider ever
  referenced, so extra dashboards named there were never mounted. The chart
  provisions exactly the dashboards in files/dashboards/. The old shipped
  default is tolerated verbatim — a values file copied from the chart carries
  it with no user intent behind it — and only a diverging list fails.
*/}}
{{- define "mcp-mesh-grafana.validateNoRemovedKeys" -}}
{{- $dashboards := .Values.grafana.dashboards | default dict -}}
{{- if hasKey $dashboards "configMaps" -}}
{{- $shipped := list "mcp-mesh-dashboards" -}}
{{- if ne (toString ($dashboards.configMaps | default list)) (toString $shipped) -}}
{{- fail (printf "grafana.dashboards.configMaps was never consumed and has been removed (set to %v, diverging from the old shipped default %v, so it would silently no-op); no volume, mount or dashboard provider ever referenced the ConfigMaps named there. This chart provisions the dashboards bundled in files/dashboards/ — to add your own, mount them yourself into /var/lib/grafana/dashboards" $dashboards.configMaps $shipped) -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as grafana.image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
The tag is upstream-versioned (no .Chart.AppVersion fallback — that tracks a
different versioning line), so an empty tag can only come from an explicit
override; fail loudly at template time instead of rendering an invalid ref.
*/}}
{{- define "mcp-mesh-grafana.image" -}}
{{- $img := .Values.grafana.image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag -}}
{{- if not $tag -}}
{{- fail "grafana.image.tag must not be empty; set the upstream image tag explicitly" -}}
{{- end -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $img.repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}
{{- end }}

{{/*
imagePullSecrets for the pod spec: global.imagePullSecrets merged with the
chart's own imagePullSecrets, deduplicated by name. Entries may be maps
({name: ...}, the Kubernetes shape) or bare strings. Renders nothing when
both lists are empty.
*/}}
{{- define "mcp-mesh-grafana.imagePullSecrets" -}}
{{- $names := list -}}
{{- $global := dig "imagePullSecrets" (list) (.Values.global | default dict) -}}
{{- range concat ($global | default list) ((.Values.grafana.imagePullSecrets) | default list) -}}
{{- $name := . -}}
{{- if kindIs "map" . -}}{{- $name = get . "name" -}}{{- end -}}
{{- if and $name (not (has $name $names)) -}}
{{- $names = append $names $name -}}
{{- end -}}
{{- end -}}
{{- if $names -}}
imagePullSecrets:
{{- range $names }}
  - name: {{ . }}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Name of the /var/lib/grafana volume — deliberately not a constant.

Kubernetes merges spec.template.spec.volumes by name, so a stable name whose
type flips between persistentVolumeClaim and emptyDir can end up carrying BOTH
under server-side apply, when the two field sets have different owners; the API
server then rejects the object with "may not specify more than 1 volume type"
and the Deployment sticks unsyncable (#1461). Encoding the type in the key turns
a grafana.persistence.enabled toggle into a remove-item + add-item on distinct
keys, which is always representable, in either direction, under Helm, Argo,
client-side and server-side apply alike.

The persistent branch keeps the historical name so installations that never
disabled persistence see no change at all.

The matching volumeMounts entry MUST use this same helper — that list is keyed
by name too, and a mount naming a volume that no longer exists is its own
invalid-Deployment failure.
*/}}
{{- define "mcp-mesh-grafana.storageVolumeName" -}}
{{- if .Values.grafana.persistence.enabled -}}storage{{- else -}}storage-ephemeral{{- end -}}
{{- end }}
