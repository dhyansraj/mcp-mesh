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
Whether the agent serves HTTP (agent.http.enabled). Unset or null means on.
Compared as a lowercased string so the quoted "false" — truthy in a plain
`if` — turns it off too; every consumer (configmap, deployment, service,
servicemonitor, ingress) goes through this one helper so they cannot
disagree. Renders "true" or nothing.
*/}}
{{- define "mcp-mesh-agent.httpEnabled" -}}
{{- $http := dig "http" (dict) (.Values.agent | default dict) | default dict -}}
{{- $v := get $http "enabled" -}}
{{- if or (not (hasKey $http "enabled")) (kindIs "invalid" $v) (ne (lower (toString $v)) "false") -}}true{{- end -}}
{{- end }}

{{/*
Whether a probe targets the container's named "http" port, which only exists
while agent.http.enabled. A non-HTTP agent serves none of /startupz, /livez
or /ready, and a probe naming a port the container does not declare makes
the Deployment invalid, so the deployment drops such probes when HTTP is off.
Probes on a numeric port or using exec/grpc are left alone.
*/}}
{{- define "mcp-mesh-agent.probeUsesHttpPort" -}}
{{- $p := . | default dict -}}
{{- if or (eq (toString (dig "httpGet" "port" "" $p)) "http") (eq (toString (dig "tcpSocket" "port" "" $p)) "http") -}}true{{- end -}}
{{- end }}

{{/*
Detect if using Python runtime (checks agent.runtime first, then image name)
*/}}
{{- define "mcp-mesh-agent.isPython" -}}
{{- if eq (toString .Values.agent.runtime) "python" }}true
{{- else if and (not .Values.agent.runtime) (contains "python" .Values.image.repository) }}true
{{- end }}
{{- end }}

{{/*
Core release-name prefix for the default core service hostnames
(<prefix>-mcp-mesh-{registry,redis,tempo}). global.coreReleaseName matches
the release name the mcp-mesh-core umbrella was installed under — agents
are separate releases, so .Release.Name cannot derive it. Explicit
hostnames (registry.host, global.redis.host, telemetryEndpoint) always win.
*/}}
{{- define "mcp-mesh-agent.corePrefix" -}}
{{- coalesce (dig "coreReleaseName" "" (.Values.global | default dict)) "mcp-core" -}}
{{- end }}

{{/*
Removed-key guard. agent.environment was dead config — no template ever
consumed it — so a values file carrying it would silently no-op while the
user expects the variables to be injected. Fail loudly with migration
guidance instead. Invoked unconditionally from the configmap.

Carve-out: the v2.4.0 chart SHIPPED a 5-entry agent.environment map as a
default (see `git show v2.4.0:helm/mcp-mesh-agent/values.yaml`). A values
file copied from it carries those entries without any user intent, so
entries exactly matching the old shipped defaults are tolerated; only a
divergent value or an extra entry — user intent that would silently
no-op — fails.

The four observability switches below were shipped as `true` and never had
an effect: mesh.tracingEnabled and mesh.metricsEnabled were never rendered,
and agent.observability.{tracing,metrics}.enabled rendered
MCP_MESH_TRACING_ENABLED / MCP_MESH_METRICS_ENABLED, which no runtime reads.
The shipped `true` is tolerated (a copied values file, no intent); any other
value is someone trying to turn something off and fails:
- the tracing switches map to the real one,
  agent.observability.distributedTracing.enabled;
- the metrics switches never had a feature behind them; scraping is opted
  into with serviceMonitor.enabled.

The keys guarded through removedKeyGuard were declared in values.yaml with
the same defaults from v1.0.0 to v3.7.x and never read by any template:
service.targetPort, agent.{version,description,capabilities,dependencies,
healthCheck,retry,performance}, agent.http.{host,cors} and podMonitor. Each
looks like it configures something (agent.http.cors.origins most of all,
which a user narrows expecting protection), so a value that differs from
the old default fails naming where that job is actually done. The shipped
defaults pass. podSecurityPolicy.enabled was removed in #1188 when it gated
podSecurityContext (now always applied); its shipped false passes, true
fails.
*/}}
{{- define "mcp-mesh-agent.validateNoRemovedKeys" -}}
{{/* Old shipped defaults, verbatim from the v2.4.0 chart values.yaml. */}}
{{- $oldEnvironmentDefaults := dict
      "MCP_MESH_DISTRIBUTED_TRACING_ENABLED" "true"
      "REDIS_URL" "redis://mcp-core-mcp-mesh-redis:6379"
      "TELEMETRY_ENDPOINT" "mcp-core-mcp-mesh-tempo:4317"
      "MCP_MESH_TRACING_ENABLED" "true"
      "MCP_MESH_METRICS_ENABLED" "true" -}}
{{- range $key, $val := (dig "environment" (dict) (.Values.agent | default dict)) | default dict -}}
{{- if not (hasKey $oldEnvironmentDefaults $key) -}}
{{- fail (printf "agent.environment was never consumed and has been removed (entry %s is not in the old shipped defaults, so it would silently no-op); add environment variables via the top-level env list (name/value entries) instead. REDIS_URL is derived from global.redis / agent.observability.distributedTracing.redisUrl" $key) -}}
{{- else if ne (toString $val) (get $oldEnvironmentDefaults $key) -}}
{{- fail (printf "agent.environment was never consumed and has been removed (%s=%q diverges from the old shipped default %q, so it would silently no-op); add environment variables via the top-level env list (name/value entries) instead. REDIS_URL is derived from global.redis / agent.observability.distributedTracing.redisUrl" $key (toString $val) (get $oldEnvironmentDefaults $key)) -}}
{{- end -}}
{{- end -}}
{{- $mesh := .Values.mesh | default dict -}}
{{- $obs := (dig "observability" (dict) (.Values.agent | default dict)) | default dict -}}
{{- $tracingMsg := "was never consumed and has been removed (set to %s, so it would silently no-op). Use agent.observability.distributedTracing.enabled — the only tracing switch the agent reads" -}}
{{- $metricsMsg := "was never consumed and has been removed (set to %s, so it would silently no-op): agents have no metrics switch. Prometheus scraping is opted into with serviceMonitor.enabled" -}}
{{- /* nil (a carried `key: ~`) carries no intent and passes, like the
       shipped `true`. */ -}}
{{- range $key, $msg := dict "tracingEnabled" $tracingMsg "metricsEnabled" $metricsMsg -}}
{{- $val := get $mesh $key -}}
{{- if and (hasKey $mesh $key) (not (kindIs "invalid" $val)) (ne (toString $val) "true") -}}
{{- fail (printf (printf "mesh.%s %s" $key $msg) (toString $val)) -}}
{{- end -}}
{{- end -}}
{{- range $switch, $msg := dict "tracing" $tracingMsg "metrics" $metricsMsg -}}
{{- $block := get $obs $switch -}}
{{- if not (hasKey $obs $switch) -}}
{{- else if kindIs "map" $block -}}
{{- range $key, $val := $block -}}
{{- if and (not (kindIs "invalid" $val)) (or (ne $key "enabled") (ne (toString $val) "true")) -}}
{{- fail (printf (printf "agent.observability.%s.%s %s" $switch $key $msg) (toString $val)) -}}
{{- end -}}
{{- end -}}
{{- else if and (not (kindIs "invalid" $block)) (ne (toString $block) "true") -}}
{{- /* A scalar in place of the block (e.g. `tracing: false`). */ -}}
{{- fail (printf (printf "agent.observability.%s %s" $switch $msg) (toString $block)) -}}
{{- end -}}
{{- end -}}
{{- $agent := .Values.agent | default dict -}}
{{- $declared := "Set it in the agent's code instead: @mesh.agent / @mesh.tool (and their TypeScript/Java equivalents) declare the version, description, capabilities and dependencies, and the agent registers them itself" -}}
{{- $removed := list
      (dict "path" "service.targetPort" "value" (dig "targetPort" nil (.Values.service | default dict)) "shipped" 8080
            "hint" "The Service always targets the container's named port \"http\"; set agent.http.port to move the listener")
      (dict "path" "agent.version" "value" (get $agent "version" | default nil) "shipped" "1.0.0" "hint" $declared)
      (dict "path" "agent.description" "value" (get $agent "description" | default nil) "shipped" "" "hint" $declared)
      (dict "path" "agent.capabilities" "value" (get $agent "capabilities" | default nil) "shipped" (list) "hint" $declared)
      (dict "path" "agent.dependencies" "value" (get $agent "dependencies" | default nil) "shipped" (list) "hint" $declared)
      (dict "path" "agent.healthCheck" "value" (get $agent "healthCheck" | default nil) "shipped" (dict "enabled" true "interval" 30 "timeout" 10)
            "hint" "Declare the health check in the agent's code; tune Kubernetes probe timing with startupProbe / livenessProbe / readinessProbe, and the heartbeat interval with the MCP_MESH_HEALTH_INTERVAL env var in the env list")
      (dict "path" "agent.retry" "value" (get $agent "retry" | default nil) "shipped" (dict "attempts" 3 "delay" 5 "maxDelay" 30)
            "hint" "The chart has no retry settings")
      (dict "path" "agent.performance" "value" (get $agent "performance" | default nil) "shipped" (dict "timeout" 30 "maxConcurrent" 10 "cacheEnabled" true "cacheTTL" 300)
            "hint" "The chart has no timeout, concurrency or cache settings; configure them in the agent's code")
      (dict "path" "agent.http.host" "value" (dig "http" "host" nil $agent) "shipped" "0.0.0.0"
            "hint" "The agent always binds 0.0.0.0 in the pod; to change the address consumers dial, set agent.advertisedHost")
      (dict "path" "agent.http.cors" "value" (dig "http" "cors" nil $agent) "shipped" (dict "enabled" true "origins" (list "*"))
            "hint" "The chart has no CORS setting, so origins were never restricted; restrict access with networkPolicy.enabled or at your ingress")
      (dict "path" "podMonitor" "value" .Values.podMonitor "shipped" (dict "enabled" false "namespace" "" "interval" "30s" "scrapeTimeout" "10s" "labels" (dict) "honorLabels" true "metricRelabelings" (list) "relabelings" (list))
            "hint" "This chart renders no PodMonitor; use serviceMonitor.enabled")
      (dict "path" "podSecurityPolicy" "value" .Values.podSecurityPolicy "shipped" (dict "enabled" false)
            "what" "has been removed"
            "hint" "PodSecurityPolicy left Kubernetes in 1.25; this flag only switched on podSecurityContext, which is now always applied, so true is already the behaviour. Adjust podSecurityContext / securityContext if the pod needs different settings") -}}
{{- range $removed -}}
{{- include "mcp-mesh-agent.removedKeyGuard" . -}}
{{- end -}}
{{- end }}

{{/*
Fail on a removed values key whose value diverges from what the chart used to
ship. Call with (dict "path" <dotted key> "value" <user value> "shipped" <old
default> "hint" <where the job lives now>), plus an optional "what" replacing
"was never read by any template and has been removed". nil and the old default carry no
intent and pass; a map recurses key by key, so a copied block passes while one
changed field fails naming itself. Scalars compare as strings (30 and "30" are
the same carried value); lists compare as JSON. Same helper as the registry
chart's removedKeyGuard.
*/}}
{{- define "mcp-mesh-agent.removedKeyGuard" -}}
{{- $v := .value -}}
{{- if kindIs "invalid" $v -}}
{{- else if and (kindIs "map" $v) (kindIs "map" .shipped) -}}
{{- range $k, $sub := $v -}}
{{- include "mcp-mesh-agent.removedKeyGuard" (dict "path" (printf "%s.%s" $.path $k) "value" $sub "shipped" (get $.shipped $k) "hint" $.hint "what" $.what) -}}
{{- end -}}
{{- else -}}
{{- $got := ternary (toJson $v) (toString $v) (or (kindIs "slice" $v) (kindIs "map" $v)) -}}
{{- $want := ternary (toJson .shipped) (toString .shipped) (or (kindIs "slice" .shipped) (kindIs "map" .shipped)) -}}
{{- if ne $got $want -}}
{{- fail (printf "%s %s (set to %s, so it would silently do nothing). %s. Remove %s from your values" .path (.what | default "was never read by any template and has been removed") $got .hint .path) -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Shared Redis settings (global.redis) as JSON — the same shape the
mcp-mesh-core umbrella shares with its datastore consumers. This chart is
standalone (not an umbrella subchart), so set the same global.redis values
on each agent release (e.g. reuse the umbrella's datastore values file).
Precedence: explicit agent.observability.distributedTracing.redisUrl >
global.redis.* > chart default.
*/}}
{{- define "mcp-mesh-agent.globalRedis" -}}
{{- dig "redis" (dict) (.Values.global | default dict) | default dict | toJson -}}
{{- end }}

{{/*
Redis scheme: rediss when global.redis.tls.enabled, redis otherwise.
*/}}
{{- define "mcp-mesh-agent.redisScheme" -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- if dig "tls" "enabled" false $g -}}rediss{{- else -}}redis{{- end -}}
{{- end }}

{{/*
Where REDIS_URL is sourced from:
  - "configmap": plain URL in the chart configmap (no credential involved —
    explicit redisUrl, composed global host without password, or the default)
  - "secret": inline global.redis.password — the URL carries a credential, so
    it renders into the chart Secret and is consumed via secretKeyRef
  - "existing-url" / "existing-password": global.redis.existingSecret modes,
    consumed via secretKeyRef in the deployment
*/}}
{{- define "mcp-mesh-agent.redisURLSource" -}}
{{- $explicit := dig "observability" "distributedTracing" "redisUrl" "" .Values.agent -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- if $explicit -}}
configmap
{{- else if $g.existingSecret -}}
{{- if $g.existingSecretUrlKey -}}existing-url{{- else -}}existing-password{{- end -}}
{{- else if $g.password -}}
secret
{{- else -}}
configmap
{{- end -}}
{{- end }}

{{/*
Effective REDIS_URL (trace publishing). An inline global password is
URL-encoded and applies over the coalesced default host (registry
semantics), so a password without a host still renders a credentialed URL —
redisURLSource classifies that combination as "secret" and the Secret must
carry the credential. Not used in the existing-secret modes.
*/}}
{{- define "mcp-mesh-agent.redisURL" -}}
{{- $explicit := dig "observability" "distributedTracing" "redisUrl" "" .Values.agent -}}
{{- if $explicit -}}
{{- $explicit -}}
{{- else -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- $auth := "" -}}
{{- if $g.password -}}
{{- $auth = printf ":%s@" ($g.password | urlquery | replace "+" "%20") -}}
{{- end -}}
{{- printf "%s://%s%s:%d" (include "mcp-mesh-agent.redisScheme" .) $auth (coalesce $g.host (printf "%s-mcp-mesh-redis" (include "mcp-mesh-agent.corePrefix" .))) (coalesce $g.port 6379 | int) -}}
{{- end -}}
{{- end }}

{{/*
REDIS_URL for the global.redis.existingSecret password-only mode: composed
via $(REDIS_PASSWORD) expansion, so the password must be URL-safe.
*/}}
{{- define "mcp-mesh-agent.composedRedisURL" -}}
{{- $g := include "mcp-mesh-agent.globalRedis" . | fromJson -}}
{{- printf "%s://:$(REDIS_PASSWORD)@%s:%d" (include "mcp-mesh-agent.redisScheme" .) ($g.host | default (printf "%s-mcp-mesh-redis" (include "mcp-mesh-agent.corePrefix" .))) (coalesce $g.port 6379 | int) -}}
{{- end }}

{{/*
Render the image reference as [registry/]repository:tag. The registry prefix
resolves as image.registry > global.imageRegistry > "" (implicit Docker Hub).
The repository path is preserved — mirror images to the same paths in a
private registry.
*/}}
{{- define "mcp-mesh-agent.image" -}}
{{- $img := .Values.image -}}
{{- $registry := $img.registry | default (dig "imageRegistry" "" (.Values.global | default dict)) | trimSuffix "/" -}}
{{- $tag := $img.tag | default .Chart.AppVersion -}}
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
{{- define "mcp-mesh-agent.imagePullSecrets" -}}
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
