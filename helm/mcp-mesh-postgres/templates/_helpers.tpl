{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-postgres.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-postgres.fullname" -}}
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
{{- define "mcp-mesh-postgres.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-postgres.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-postgres.chart" . }}
{{ include "mcp-mesh-postgres.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: database
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-postgres.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-postgres.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Provisioned database / credentials. Precedence per field: explicit
postgres.* > global.postgres.* (the mcp-mesh-core umbrella shares one
global.postgres block, so the bundled database is provisioned with the same
credentials every consumer connects with) > chart default.
*/}}
{{- define "mcp-mesh-postgres.database" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce .Values.postgres.database $g.name "mcpmesh" -}}
{{- end }}

{{- define "mcp-mesh-postgres.username" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce .Values.postgres.username $g.username "mcpmesh" -}}
{{- end }}

{{/*
Inline provisioning password: explicit postgres.password > global.postgres.password.
Empty means no inline password is configured — the chart then auto-generates
one (see secret.yaml) unless an existing secret supplies it.
*/}}
{{- define "mcp-mesh-postgres.password" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- or .Values.postgres.password $g.password "" -}}
{{- end }}

{{/*
Existing secret holding the provisioning password (postgres.existingSecret >
global.postgres.existingSecret — the same secret every consumer reads its
credential from in the mcp-mesh-core umbrella).
*/}}
{{- define "mcp-mesh-postgres.existingSecret" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- or .Values.postgres.existingSecret $g.existingSecret "" -}}
{{- end }}

{{- define "mcp-mesh-postgres.existingSecretPasswordKey" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce .Values.postgres.existingSecretPasswordKey $g.existingSecretPasswordKey "password" -}}
{{- end }}

{{/*
Name of the chart-managed credentials Secret (holds the inline or the
auto-generated provisioning password under the "password" key).
global.postgres.generatedSecretName overrides; the default mirrors the chart
fullname so sibling consumers in the mcp-mesh-core umbrella can derive the
same name from the shared .Release.Name.
*/}}
{{- define "mcp-mesh-postgres.credentialsSecretName" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- coalesce $g.generatedSecretName (printf "%s-credentials" (include "mcp-mesh-postgres.fullname" .)) -}}
{{- end }}

{{/*
Guard for the bundled-postgres + existingSecret combination. Provisioning now
consumes the referenced secret itself (POSTGRES_PASSWORD via secretKeyRef), so
sharing one external secret between provisioning and the consumers is
supported. The one remaining mismatch is the full-DSN mode: with
existingSecretUrlKey set, consumers read a complete DSN while provisioning
still needs a bare password key — that only lines up when the user explicitly
points existingSecretPasswordKey at a password key stored alongside the DSN.
Fail otherwise. This chart only renders when it is enabled (postgres.enabled
in the mcp-mesh-core umbrella), so the guard fires exactly on the broken
combination. Invoked unconditionally from the statefulset.
*/}}
{{- define "mcp-mesh-postgres.validateCredentialSource" -}}
{{- $g := dig "postgres" (dict) (.Values.global | default dict) | default dict -}}
{{- $explicitPasswordKey := or .Values.postgres.existingSecretPasswordKey $g.existingSecretPasswordKey "" -}}
{{- if and (include "mcp-mesh-postgres.existingSecret" .) $g.existingSecretUrlKey (not $explicitPasswordKey) -}}
{{- fail "global.postgres.existingSecretUrlKey cannot be combined with the bundled PostgreSQL chart unless existingSecretPasswordKey is also set: consumers read the full DSN from the secret, but provisioning needs a bare password key holding the same password the DSN carries. Set global.postgres.existingSecretPasswordKey (the key must exist in the secret alongside the DSN), or disable the bundled subchart (postgres.enabled=false) to use an external database" -}}
{{- end -}}
{{- /* Explicitly disabling auto-generation without supplying a credential
       leaves consumers composing empty-password DSNs while provisioning
       still has to generate one — they could never match. */ -}}
{{- if and (hasKey $g "generatedSecret") (not $g.generatedSecret) (not (include "mcp-mesh-postgres.password" .)) (not (include "mcp-mesh-postgres.existingSecret" .)) -}}
{{- fail "global.postgres.generatedSecret=false requires global.postgres.password or global.postgres.existingSecret while the bundled PostgreSQL chart is enabled: provisioning must have a password, but consumers would compose credential-less DSNs. Set a credential, re-enable generatedSecret, or disable the bundled subchart (postgres.enabled=false)" -}}
{{- end -}}
{{- /* In generated-secret mode the consumers (registry, UI) derive the
       Secret name from .Release.Name — they cannot see this subchart's name
       overrides — so a nameOverride/fullnameOverride here silently renames
       the generated Secret and every consumer references one that does not
       exist (CreateContainerConfigError at pod start, no template error).
       global.postgres.generatedSecretName is the escape hatch: it is
       followed by this chart and all consumers alike. */ -}}
{{- if and ($g.generatedSecret | default false) (not (include "mcp-mesh-postgres.password" .)) (not (include "mcp-mesh-postgres.existingSecret" .)) (not $g.generatedSecretName) (or .Values.nameOverride .Values.fullnameOverride) -}}
{{- fail (printf "nameOverride/fullnameOverride on the bundled PostgreSQL chart renames the auto-generated credentials Secret to %q, but consumers derive the default name from the release name and would reference a Secret that does not exist. Set global.postgres.generatedSecretName=%q so every chart follows the override" (include "mcp-mesh-postgres.credentialsSecretName" .) (include "mcp-mesh-postgres.credentialsSecretName" .)) -}}
{{- end -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
*/}}
{{- define "mcp-mesh-postgres.image" -}}
{{- $img := .Values.image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag -}}
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
{{- define "mcp-mesh-postgres.imagePullSecrets" -}}
{{- $names := list -}}
{{- $global := dig "imagePullSecrets" (list) (.Values.global | default dict) -}}
{{- range concat ($global | default list) ((.Values.imagePullSecrets) | default list) -}}
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
