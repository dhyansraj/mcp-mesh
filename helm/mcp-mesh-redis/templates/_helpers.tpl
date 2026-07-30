{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-mesh-redis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mcp-mesh-redis.fullname" -}}
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
{{- define "mcp-mesh-redis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-mesh-redis.labels" -}}
helm.sh/chart: {{ include "mcp-mesh-redis.chart" . }}
{{ include "mcp-mesh-redis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: cache
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-mesh-redis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-mesh-redis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Reject global.redis credentials while this bundled chart renders: this chart
starts redis-server without AUTH (no requirepass plumbing), so a
global.redis.password / global.redis.existingSecret credential renders into
every consumer's REDIS_URL but the bundled server would reject (or ignore)
it — a silent runtime auth failure. This chart only renders when it is
enabled (redis.enabled in the mcp-mesh-core umbrella), so the guard fires
exactly on the broken combination. Invoked unconditionally from the
deployment.
*/}}
{{- define "mcp-mesh-redis.validateCredentialSource" -}}
{{- $g := dig "redis" (dict) (.Values.global | default dict) | default dict -}}
{{- if or $g.password $g.existingSecret -}}
{{- fail "global.redis.password / global.redis.existingSecret cannot be combined with the bundled Redis chart: it runs without AUTH, so the credential every consumer connects with can never work. Disable the bundled subchart (redis.enabled=false) and point global.redis at an external Redis, or drop the global.redis credentials" -}}
{{- end -}}
{{- end }}

{{/*
Persistence guard + removed-key guards, same convention as
mcp-mesh-registry.validateNoRemovedKeys: a key no template ever consumed is
deleted rather than left to no-op silently, and a values file still carrying
one fails with migration guidance instead. Invoked unconditionally from the
deployment.

This chart has no PVC template and never had one, so persistence.enabled used
to render a claimName derived from the release that nothing ever created — the
pod stayed Pending forever on a claim no controller would bind. The four
provisioning keys beside it (storageClass, accessMode, size, annotations)
configured that absent PVC and so were read by nothing at all.

What survives is the case that actually worked: a claim created out of band and
mounted by name. That is now spelled persistence.existingClaim (the same key
name mcp-mesh-agent uses), and enabled without it is a template-time error
rather than a Pending pod.

The removed keys are tolerated at their old shipped values — a values file
copied from this chart or from the v3.x mcp-mesh-core umbrella (which shipped
mcp-mesh-redis.persistence.enabled: false) carries them with no intent behind
them — and only a diverging value fails.
*/}}
{{- define "mcp-mesh-redis.validateNoRemovedKeys" -}}
{{- $p := .Values.persistence | default dict -}}
{{/* Old shipped defaults, verbatim from this chart's values.yaml. */}}
{{- $shipped := dict "storageClass" "" "accessMode" "ReadWriteOnce" "size" "8Gi" -}}
{{- range $key, $default := $shipped -}}
{{- if and (hasKey $p $key) (ne (toString (get $p $key)) $default) -}}
{{- fail (printf "persistence.%s was never consumed and has been removed (set to %q, diverging from the old shipped default %q, so it would silently no-op): this chart renders no PersistentVolumeClaim, so it configured nothing. Create the claim yourself with the size and class you want, then mount it with persistence.existingClaim" $key (toString (get $p $key)) $default) -}}
{{- end -}}
{{- end -}}
{{- if get $p "annotations" -}}
{{- fail "persistence.annotations was never consumed and has been removed: this chart renders no PersistentVolumeClaim to annotate. Annotate the claim you create yourself and mount it with persistence.existingClaim" -}}
{{- end -}}
{{- if and $p.enabled (not $p.existingClaim) -}}
{{- fail (printf "persistence.enabled requires persistence.existingClaim: this chart renders no PersistentVolumeClaim, so enabling persistence without naming an existing claim leaves the pod Pending forever on one nothing creates. Create the claim (any size/class you want) and name it here — if you are upgrading a release that already had persistence.enabled, the claim it referenced was %q. Redis here is an evicting cache on an emptyDir by design; leave persistence.enabled false unless you deliberately want its /data to survive a restart" (include "mcp-mesh-redis.fullname" .)) -}}
{{- end -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
The tag is upstream-versioned (no .Chart.AppVersion fallback — that tracks a
different versioning line), so an empty tag can only come from an explicit
override; fail loudly at template time instead of rendering an invalid ref.
*/}}
{{- define "mcp-mesh-redis.image" -}}
{{- $img := .Values.image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag -}}
{{- if not $tag -}}
{{- fail "image.tag must not be empty; set the upstream image tag explicitly" -}}
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
{{- define "mcp-mesh-redis.imagePullSecrets" -}}
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
