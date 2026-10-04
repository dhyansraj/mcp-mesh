#!/usr/bin/env python3
"""Render the helm/ charts with NON-DEFAULT values and assert every template-time
guard still behaves: each guard's fail path fails with its own message, and the
pass path next to it still renders.

scripts/check_helm_pss.py renders defaults only, and a guard is by construction
inert on the default path — `mcp-mesh-core.validateNamespaceResourcePolicy` and
`mcp-mesh-grafana.validateCredentialSource` both emit nothing at all until a
values file trips them. A defaults-only render therefore cannot tell a working
guard from a broken one, or from one that was deleted: every one of these
`fail` calls would stay green forever.

Each case declares the values that reach the guard and what must happen:

  expect_fail="<substring>"  helm template must exit non-zero AND say this
  expect_fail=None           helm template must succeed (the pass path)

The substring matters as much as the exit code. A guard rewritten to fire on
the wrong condition still fails the render, just with someone else's message.

A pass-path case may additionally pin which objects that render contains:

  requires_kind="Namespace"  the render must contain an object of this kind
  forbids_kind="Namespace"   it must not

That is for values whose whole purpose is to add or remove a resource — an
opt-in object silently becoming opt-out (or the reverse) is a behaviour change
a non-empty render cannot detect.

It may also pin the container probe paths:

  probe_paths={"startupProbe": "/startupz", "livenessProbe": "/livez",
               "readinessProbe": "/ready"}

Issue #1467: liveness and readiness pointing at the SAME url is the bug —
a dependency outage that should only make an agent unready instead restarts
the pod, which cannot fix the dependency and launders the failing agent back
into resolution. A values default is one careless edit away from collapsing
back, and every render stays green when it does. Declaring the paths makes
that edit fail here. Two declared probes sharing a path is additionally
rejected outright, whatever the declared paths were.

And it may pin rendered configuration:

  config_data={"MCP_MESH_HTTP_ENABLED": "false"}
      some rendered ConfigMap must carry each key with exactly this value
  forbids_env=("AUTH_TOKENS",)
      no ConfigMap data key and no container env entry may use these names
  requires_init_container="wait-for-db" / forbids_init_container="wait-for-db"
      a workload must (or must not) declare an init container of this name

Issue #1573: Sprig `default` treats false as unset, so `enabled: false`
rendered "true" and every render stayed green. Pinning the rendered value of
each boolean, both set to false and left unset, is what catches a `| default
true` creeping back. The forbidden names are env vars the charts used to
inject that no runtime reads.

Issue #1574 adds four more:

  env_values={"DATABASE_URL": "/data/mcp_mesh_registry.db"}
      some workload container must set each env var to exactly this value
  config_contains={"datasources.yaml": "http://x-mcp-mesh-tempo:3200"}
      some rendered ConfigMap key must contain this substring
  probe_specs={"livenessProbe": {...}, "startupProbe": None}
      every workload container's probe must equal the dict exactly (None:
      must be absent). Unlike probe_paths this pins the whole spec, for the
      registry whose probes deliberately share /health.
  forbids_kinds=("Service", "Ingress")
      the render must contain none of these kinds
  env_unique=("DATABASE_URL",)
      no workload container may declare one of these env names twice
  routes_to=(("mcp-mesh-core", "mcp-core", ()), ...)
      every Ingress backend must name a Service (and port) that the listed
      charts actually render under those release names. This is what proves
      a documented install sequence routes: the Ingress, core and agent
      charts each render fine on their own while pointing at each other's
      wrong names.

Usage: python3 scripts/check_helm_render_matrix.py  (run from anywhere)
Exit code 0 = every case behaved as declared.
"""

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_helm_pss import HELM_DIR, build_dependencies  # noqa: E402

# The five entries the v2.4.0 chart shipped as agent.environment defaults. A
# values file copied from that release carries them without user intent, so the
# removed-key guard tolerates them verbatim and only fails on divergence.
V240_AGENT_ENVIRONMENT = {
    "MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "true",
    "REDIS_URL": "redis://mcp-core-mcp-mesh-redis:6379",
    "TELEMETRY_ENDPOINT": "mcp-core-mcp-mesh-tempo:4317",
    "MCP_MESH_TRACING_ENABLED": "true",
    "MCP_MESH_METRICS_ENABLED": "true",
}


@dataclass(frozen=True)
class Case:
    chart: str
    name: str
    values: dict
    expect_fail: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    requires_kind: str | None = None
    forbids_kind: str | None = None
    probe_paths: dict[str, str] | None = None
    config_data: dict[str, str] | None = None
    forbids_env: tuple[str, ...] = field(default_factory=tuple)
    requires_init_container: str | None = None
    forbids_init_container: str | None = None
    env_values: dict[str, str] | None = None
    config_contains: dict[str, str] | None = None
    probe_specs: dict[str, dict | None] | None = None
    forbids_kinds: tuple[str, ...] = field(default_factory=tuple)
    env_unique: tuple[str, ...] = field(default_factory=tuple)
    release: str = "render-matrix"
    routes_to: tuple[tuple[str, str, tuple[str, ...]], ...] = field(
        default_factory=tuple
    )


# Env vars the charts once injected that no runtime reads (issue #1573).
DEAD_AGENT_ENV = (
    "MCP_MESH_TRACING_ENABLED",
    "MCP_MESH_METRICS_ENABLED",
    "MCP_MESH_DYNAMIC_UPDATES",
    "MCP_MESH_UPDATE_STRATEGY",
)
DEAD_REGISTRY_ENV = (
    "AUTH_TOKENS",
    "DATABASE_TYPE",
    "DATABASE_PATH",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USERNAME",
)

# The registry chart's former security.auth block, verbatim from values.yaml
# before its removal. A copied values file carries it without intent.
SHIPPED_REGISTRY_AUTH = {
    "enabled": False,
    "type": "token",
    "tokens": [],
    "existingSecret": "",
    "secretKey": "tokens",
}
REGISTRY_AUTH_REMOVED = "has been removed: the registry has no token authentication"

# The registry probes as deployment.yaml hard-coded them before #1574 wired the
# values: the default render must keep exactly these.
REGISTRY_PROBES_BEFORE_1574 = {
    "livenessProbe": {
        "httpGet": {"path": "/health", "port": "http"},
        "initialDelaySeconds": 30,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "failureThreshold": 3,
    },
    "readinessProbe": {
        "httpGet": {"path": "/health", "port": "http"},
        "initialDelaySeconds": 10,
        "periodSeconds": 5,
        "timeoutSeconds": 3,
        "failureThreshold": 3,
    },
    "startupProbe": {
        "httpGet": {"path": "/health", "port": "http"},
        "initialDelaySeconds": 5,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "failureThreshold": 30,
    },
}
NO_PROBES = {"startupProbe": None, "livenessProbe": None, "readinessProbe": None}

# Removed values keys, each set to a value diverging from what the chart
# shipped (#1574). Every one must fail naming itself.
REMOVED_REGISTRY_KEYS = [
    ("workloadType", {"workloadType": "StatefulSet"}),
    ("service.targetPort", {"service": {"targetPort": 9000}}),
    ("registry.logging.format", {"registry": {"logging": {"format": "text"}}}),
    ("registry.healthCheck.interval", {"registry": {"healthCheck": {"interval": 15}}}),
    (
        "registry.performance.maxConnections",
        {"registry": {"performance": {"maxConnections": 50}}},
    ),
    (
        "registry.performance.connectionTimeout",
        {"registry": {"performance": {"connectionTimeout": 5}}},
    ),
    (
        "registry.performance.requestTimeout",
        {"registry": {"performance": {"requestTimeout": 5}}},
    ),
    ("podMonitor.enabled", {"podMonitor": {"enabled": True}}),
    (
        "registry.database.existingSecretUsernameKey",
        {"registry": {"database": {"existingSecretUsernameKey": "user"}}},
    ),
]
# The same keys at the values every release from v1.0.0 to v3.7.x shipped.
SHIPPED_REMOVED_REGISTRY_KEYS = {
    "workloadType": "Deployment",
    "service": {"targetPort": 8000},
    "registry": {
        "logging": {"format": "json"},
        "healthCheck": {"enabled": True, "interval": 30, "timeout": 10},
        "performance": {
            "maxConnections": 1000,
            "connectionTimeout": 30,
            "requestTimeout": 60,
        },
        "database": {"existingSecretUsernameKey": "username"},
    },
    "podMonitor": {
        "enabled": False,
        "namespace": "",
        "interval": "30s",
        "scrapeTimeout": "10s",
        "labels": {},
        "honorLabels": True,
        "metricRelabelings": [],
        "relabelings": [],
    },
}
REMOVED_AGENT_KEYS = [
    ("service.targetPort", {"service": {"targetPort": 9000}}),
    ("agent.version", {"agent": {"version": "2.0.0"}}),
    ("agent.description", {"agent": {"description": "greets people"}}),
    ("agent.capabilities", {"agent": {"capabilities": [{"name": "greeting"}]}}),
    ("agent.dependencies", {"agent": {"dependencies": [{"name": "translator"}]}}),
    ("agent.healthCheck.interval", {"agent": {"healthCheck": {"interval": 15}}}),
    ("agent.retry.attempts", {"agent": {"retry": {"attempts": 5}}}),
    ("agent.performance.timeout", {"agent": {"performance": {"timeout": 60}}}),
    ("agent.http.host", {"agent": {"http": {"host": "127.0.0.1"}}}),
    (
        "agent.http.cors.origins",
        {"agent": {"http": {"cors": {"origins": ["https://app.example.com"]}}}},
    ),
    ("podMonitor.enabled", {"podMonitor": {"enabled": True}}),
    ("podSecurityPolicy.enabled", {"podSecurityPolicy": {"enabled": True}}),
]
SHIPPED_REMOVED_AGENT_KEYS = {
    "service": {"targetPort": 8080},
    "agent": {
        "version": "1.0.0",
        "description": "",
        "capabilities": [],
        "dependencies": [],
        "healthCheck": {"enabled": True, "interval": 30, "timeout": 10},
        "retry": {"attempts": 3, "delay": 5, "maxDelay": 30},
        "performance": {
            "timeout": 30,
            "maxConcurrent": 10,
            "cacheEnabled": True,
            "cacheTTL": 300,
        },
        "http": {"host": "0.0.0.0", "cors": {"enabled": True, "origins": ["*"]}},
    },
    "podMonitor": dict(SHIPPED_REMOVED_REGISTRY_KEYS["podMonitor"]),
    "podSecurityPolicy": {"enabled": False},
}
# What a mcp-mesh-core install per its README and an agent installed as
# `helm install hello-world mcp-mesh-agent` render, for the ingress routing
# cases.
CORE_AT_MCP_CORE = ("mcp-mesh-core", "mcp-core", ("--set", "ui.enabled=true"))
AGENT_HELLO_WORLD = ("mcp-mesh-agent", "hello-world", ())


CASES: list[Case] = [
    # --- mcp-mesh-core: Namespace resource-policy guard -------------------
    Case(
        "mcp-mesh-core",
        "commonAnnotations may not override the Namespace's keep policy",
        {"commonAnnotations": {"helm.sh/resource-policy": "delete"}},
        expect_fail="blast radius",
    ),
    Case(
        "mcp-mesh-core",
        "an explicit keep is a tolerated no-op",
        {"commonAnnotations": {"helm.sh/resource-policy": "keep"}},
    ),
    # Both guards live in namespace.yaml, above its `{{- if .Values.namespaceCreate }}`
    # so they run whether or not the Namespace renders. namespaceCreate now
    # defaults to false, which means that `if` is closed on virtually every
    # install and the guards are the file's only output — pin the flag
    # explicitly on one fail case each, so moving the includes below the `if`
    # (or deleting the file once it renders nothing) is caught here rather
    # than in the field.
    Case(
        "mcp-mesh-core",
        "the resource-policy guard still fires with namespaceCreate off",
        {
            "namespaceCreate": False,
            "commonAnnotations": {"helm.sh/resource-policy": "delete"},
        },
        expect_fail="blast radius",
    ),
    Case(
        "mcp-mesh-core",
        "the removed-key guard still fires with namespaceCreate off",
        {"namespaceCreate": False, "networkPolicies": {"enabled": True}},
        expect_fail="networkPolicies.enabled was never consumed",
    ),
    # --- mcp-mesh-core: the Namespace object is opt-in --------------------
    # A release that renders a Namespace it did not create cannot be installed
    # (Helm's ownership check), and one that stops rendering a Namespace it did
    # DELETES it, cascading to everything inside. Both directions are silent,
    # so pin the default explicitly.
    Case(
        "mcp-mesh-core",
        "no Namespace object at the shipped default",
        {},
        forbids_kind="Namespace",
    ),
    Case(
        "mcp-mesh-core",
        "...and one only when namespaceCreate is turned on",
        {"namespaceCreate": True},
        requires_kind="Namespace",
    ),
    # --- mcp-mesh-core: removed-key guards --------------------------------
    Case(
        "mcp-mesh-core",
        "networkPolicies.enabled was removed",
        {"networkPolicies": {"enabled": True}},
        expect_fail="networkPolicies.enabled was never consumed",
    ),
    Case(
        "mcp-mesh-core",
        "serviceMonitors.enabled was removed",
        {"serviceMonitors": {"enabled": True}},
        expect_fail="serviceMonitors.enabled was never consumed",
    ),
    Case(
        "mcp-mesh-core",
        "global.coreReleaseName was removed",
        {"global": {"coreReleaseName": "platform"}},
        expect_fail="names a different release than this one",
    ),
    Case(
        "mcp-mesh-core",
        "the shipped coreReleaseName default is grandfathered",
        {"global": {"coreReleaseName": "mcp-core"}},
    ),
    # --- mcp-mesh-grafana (through the umbrella): credential source -------
    Case(
        "mcp-mesh-core",
        "grafana generatedSecret=false with no credential",
        {"mcp-mesh-grafana": {"grafana": {"config": {"generatedSecret": False}}}},
        expect_fail="grafana.config.generatedSecret=false requires",
    ),
    Case(
        "mcp-mesh-core",
        "grafana generatedSecret=false with existingSecret",
        {
            "mcp-mesh-grafana": {
                "grafana": {
                    "config": {"generatedSecret": False, "existingSecret": "gf-admin"}
                }
            }
        },
    ),
    Case(
        "mcp-mesh-core",
        "grafana generatedSecret=false with an inline adminPassword",
        {
            "mcp-mesh-grafana": {
                "grafana": {
                    "config": {"generatedSecret": False, "adminPassword": "s3cret"}
                }
            }
        },
    ),
    # --- mcp-mesh-grafana: securityContext migration + image tag ----------
    Case(
        "mcp-mesh-core",
        "pod-only fields rejected in grafana.securityContext",
        {"mcp-mesh-grafana": {"grafana": {"securityContext": {"fsGroup": 472}}}},
        expect_fail="belong in grafana.podSecurityContext",
    ),
    Case(
        "mcp-mesh-core",
        "the same field is accepted in grafana.podSecurityContext",
        {"mcp-mesh-grafana": {"grafana": {"podSecurityContext": {"fsGroup": 472}}}},
    ),
    Case(
        "mcp-mesh-core",
        "an emptied grafana image tag",
        {"mcp-mesh-grafana": {"grafana": {"image": {"tag": ""}}}},
        expect_fail="grafana.image.tag must not be empty",
    ),
    # --- mcp-mesh-registry (through the umbrella): trust backend guard ----
    # Issue #1600: the registry refuses to start in any TLS mode other than
    # off without a trust backend, so the chart fails the render instead of
    # shipping a crash-looping pod.
    Case(
        "mcp-mesh-core",
        "registry TLS mode auto with no trust backend",
        {"mcp-mesh-registry": {"registry": {"security": {"tls": {"mode": "auto"}}}}},
        expect_fail="registry.security.tls.mode=auto requires registry.security.trust.backend",
    ),
    Case(
        "mcp-mesh-core",
        "registry TLS mode strict with no trust backend",
        {"mcp-mesh-registry": {"registry": {"security": {"tls": {"mode": "strict"}}}}},
        expect_fail="registry.security.tls.mode=strict requires registry.security.trust.backend",
    ),
    Case(
        "mcp-mesh-core",
        "...and the same mode once a trust backend is named",
        {
            "mcp-mesh-registry": {
                "registry": {
                    "security": {
                        "tls": {"mode": "auto"},
                        "trust": {"backend": "filestore"},
                    }
                }
            }
        },
    ),
    # --- mcp-mesh-postgres (through the umbrella) -------------------------
    Case(
        "mcp-mesh-core",
        "postgres generatedSecret=false with no credential",
        {"global": {"postgres": {"generatedSecret": False}}},
        expect_fail="global.postgres.generatedSecret=false requires",
    ),
    Case(
        "mcp-mesh-core",
        "postgres generatedSecret=false with an inline password",
        {"global": {"postgres": {"generatedSecret": False, "password": "pw"}}},
    ),
    Case(
        "mcp-mesh-core",
        "a full-DSN existing secret with no bare password key",
        {
            "global": {
                "postgres": {"existingSecret": "pg", "existingSecretUrlKey": "dsn"}
            }
        },
        expect_fail="existingSecretUrlKey cannot be combined",
    ),
    Case(
        "mcp-mesh-core",
        "...and the same secret once a password key is named",
        {
            "global": {
                "postgres": {
                    "existingSecret": "pg",
                    "existingSecretUrlKey": "dsn",
                    "existingSecretPasswordKey": "password",
                }
            }
        },
    ),
    Case(
        "mcp-mesh-core",
        "a name override that renames the generated postgres secret",
        {"mcp-mesh-postgres": {"nameOverride": "db"}},
        expect_fail="generatedSecretName",
    ),
    Case(
        "mcp-mesh-core",
        "...and the same override once generatedSecretName follows it",
        {
            "mcp-mesh-postgres": {"nameOverride": "db"},
            "global": {"postgres": {"generatedSecretName": "mcp-core-db-credentials"}},
        },
    ),
    Case(
        "mcp-mesh-core",
        "an external postgres with the bundled subchart disabled",
        {
            "postgres": {"enabled": False},
            "global": {
                "postgres": {
                    "host": "pg.example.internal",
                    "password": "pw",
                    "sslmode": "require",
                }
            },
        },
    ),
    # --- mcp-mesh-redis (through the umbrella) ----------------------------
    Case(
        "mcp-mesh-core",
        "redis credentials against the AUTH-less bundled server",
        {"global": {"redis": {"password": "pw"}}},
        expect_fail="cannot be combined with the bundled Redis chart",
    ),
    Case(
        "mcp-mesh-core",
        "...and the same credentials once redis points somewhere external",
        {
            "redis": {"enabled": False},
            "global": {"redis": {"host": "redis.example.internal", "password": "pw"}},
        },
    ),
    Case(
        "mcp-mesh-core",
        "redis persistence enabled with no claim to mount",
        {"mcp-mesh-redis": {"persistence": {"enabled": True}}},
        expect_fail="persistence.enabled requires persistence.existingClaim",
    ),
    Case(
        "mcp-mesh-core",
        "...and the same once an existing claim is named",
        {
            "mcp-mesh-redis": {
                "persistence": {"enabled": True, "existingClaim": "redis-data"}
            }
        },
    ),
    Case(
        "mcp-mesh-core",
        "a redis PVC size that never provisioned anything",
        {"mcp-mesh-redis": {"persistence": {"size": "20Gi"}}},
        expect_fail="persistence.size was never consumed",
    ),
    Case(
        "mcp-mesh-core",
        "the shipped redis persistence defaults are grandfathered",
        {
            "mcp-mesh-redis": {
                "persistence": {
                    "enabled": False,
                    "storageClass": "",
                    "accessMode": "ReadWriteOnce",
                    "size": "8Gi",
                    "annotations": {},
                }
            }
        },
    ),
    # --- mcp-mesh-grafana: removed dashboard key --------------------------
    Case(
        "mcp-mesh-core",
        "grafana dashboards.configMaps that never mounted anything",
        {"mcp-mesh-grafana": {"grafana": {"dashboards": {"configMaps": ["mine"]}}}},
        expect_fail="grafana.dashboards.configMaps was never consumed",
    ),
    Case(
        "mcp-mesh-core",
        "the shipped dashboards.configMaps default is grandfathered",
        {
            "mcp-mesh-grafana": {
                "grafana": {"dashboards": {"configMaps": ["mcp-mesh-dashboards"]}}
            }
        },
    ),
    # --- mcp-mesh-ui (through the umbrella) -------------------------------
    Case(
        "mcp-mesh-core",
        "an unrecognised postgres sslmode",
        {"ui": {"enabled": True}, "global": {"postgres": {"sslmode": "yes-please"}}},
        expect_fail="global.postgres.sslmode must be one of",
    ),
    Case(
        "mcp-mesh-core",
        "a recognised postgres sslmode",
        {"ui": {"enabled": True}, "global": {"postgres": {"sslmode": "verify-full"}}},
    ),
    # --- mcp-mesh-agent (standalone chart) --------------------------------
    Case(
        "mcp-mesh-agent",
        "an agent.environment entry that was never consumed",
        {"agent": {"environment": {"MY_API_KEY": "abc"}}},
        expect_fail="agent.environment was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "an agent.environment default carried forward with a changed value",
        {"agent": {"environment": {"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "false"}}},
        expect_fail="diverges from the old shipped default",
    ),
    Case(
        "mcp-mesh-agent",
        "the v2.4.0 agent.environment defaults verbatim",
        {"agent": {"environment": dict(V240_AGENT_ENVIRONMENT)}},
    ),
    # --- mcp-mesh-agent: booleans honour an explicit false (#1573) ---------
    Case(
        "mcp-mesh-agent",
        "agent booleans render true when unset, and no dead env is injected",
        {},
        config_data={
            "MCP_MESH_HTTP_ENABLED": "true",
            "MCP_MESH_ENABLED": "true",
            "MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "true",
        },
        forbids_env=DEAD_AGENT_ENV,
    ),
    Case(
        "mcp-mesh-agent",
        "agent.http.enabled=false renders false",
        {"agent": {"http": {"enabled": False}}},
        config_data={"MCP_MESH_HTTP_ENABLED": "false"},
    ),
    Case(
        "mcp-mesh-agent",
        "mesh.enabled=false renders false",
        {"mesh": {"enabled": False}},
        config_data={"MCP_MESH_ENABLED": "false"},
    ),
    Case(
        "mcp-mesh-agent",
        "agent distributedTracing.enabled=false renders false",
        {"agent": {"observability": {"distributedTracing": {"enabled": False}}}},
        config_data={"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "false"},
    ),
    # --- mcp-mesh-agent: removed observability switches -------------------
    Case(
        "mcp-mesh-agent",
        "mesh.tracingEnabled=false never turned tracing off",
        {"mesh": {"tracingEnabled": False}},
        expect_fail="mesh.tracingEnabled was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "mesh.metricsEnabled=false never turned anything off",
        {"mesh": {"metricsEnabled": False}},
        expect_fail="mesh.metricsEnabled was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "agent.observability.tracing.enabled=false never turned tracing off",
        {"agent": {"observability": {"tracing": {"enabled": False}}}},
        expect_fail="agent.observability.tracing.enabled was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "agent.observability.metrics.enabled=false never turned anything off",
        {"agent": {"observability": {"metrics": {"enabled": False}}}},
        expect_fail="agent.observability.metrics.enabled was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "a scalar agent.observability.tracing=false gets the guided message",
        {"agent": {"observability": {"tracing": False}}},
        expect_fail="agent.observability.tracing was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "a scalar agent.observability.metrics=false gets the guided message",
        {"agent": {"observability": {"metrics": False}}},
        expect_fail="agent.observability.metrics was never consumed",
    ),
    Case(
        "mcp-mesh-agent",
        "scalar true and null observability switches carry no intent",
        {
            "mesh": {"tracingEnabled": None, "metricsEnabled": None},
            "agent": {"observability": {"tracing": True, "metrics": None}},
        },
    ),
    Case(
        "mcp-mesh-agent",
        "the shipped observability switch defaults are grandfathered",
        {
            "mesh": {"tracingEnabled": True, "metricsEnabled": True},
            "agent": {
                "observability": {
                    "tracing": {"enabled": True},
                    "metrics": {"enabled": True},
                }
            },
        },
        forbids_env=DEAD_AGENT_ENV,
    ),
    # --- mcp-mesh-agent: every probe is a different URL --------------------
    # Issues #1467/#1468: liveness may only fail for something a restart can
    # fix, so it points at /livez — the process is serving, and nothing else.
    # A liveness probe that consults a dependency restarts the pod for an
    # outage a restart cannot fix, then launders the still-failing agent back
    # into resolution. That history is why liveness must never grow a
    # dependency check.
    #
    # RFC #1502 split the other two apart. /ready reports whether the mesh
    # runtime is up and never carries the user's health verdict: a dependency
    # outage now fails NO probe: it pauses the heartbeat, the registry ages
    # the agent out and routing moves. /startupz is the fatal-configuration
    # check, and it gets the startup probe because that probe also restarts
    # the container — an agent that can never serve (unusable config, missing
    # credential) is held in CrashLoopBackOff where the cause is visible,
    # rather than coming up and registering broken. The verdict itself is
    # served at /health, which no probe reads.
    Case(
        "mcp-mesh-agent",
        "probes at the shipped defaults point at distinct endpoints",
        {},
        probe_paths={
            "startupProbe": "/startupz",
            "livenessProbe": "/livez",
            "readinessProbe": "/ready",
        },
    ),
    # --- mcp-mesh-ui (standalone chart): booleans (#1573) ----------------
    Case(
        "mcp-mesh-ui",
        "ui tracing renders true when unset",
        {},
        config_data={"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "true"},
    ),
    Case(
        "mcp-mesh-ui",
        "ui.tracing.enabled=false renders false",
        {"ui": {"tracing": {"enabled": False}}},
        config_data={"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "false"},
    ),
    # --- mcp-mesh-registry (standalone chart): booleans (#1573) ----------
    Case(
        "mcp-mesh-registry",
        "registry booleans at their defaults, and no dead env is injected",
        {},
        config_data={
            "MCP_MESH_DEBUG_MODE": "true",
            "MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "true",
        },
        forbids_env=DEAD_REGISTRY_ENV,
        requires_init_container="wait-for-db",
    ),
    # The default render is postgres, so DATABASE_PATH (sqlite-only) can
    # only reappear on this path.
    Case(
        "mcp-mesh-registry",
        "no dead env is injected on sqlite",
        {"registry": {"database": {"type": "sqlite"}}},
        forbids_env=DEAD_REGISTRY_ENV,
    ),
    Case(
        "mcp-mesh-registry",
        "registry.logging.debug=false renders false",
        {"registry": {"logging": {"debug": False}}},
        config_data={"MCP_MESH_DEBUG_MODE": "false"},
    ),
    Case(
        "mcp-mesh-registry",
        "registry distributedTracing.enabled=false renders false",
        {"registry": {"observability": {"distributedTracing": {"enabled": False}}}},
        config_data={"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "false"},
    ),
    Case(
        "mcp-mesh-registry",
        "registry.database.waitForDatabase=false drops the init container",
        {"registry": {"database": {"waitForDatabase": False}}},
        forbids_init_container="wait-for-db",
    ),
    # A quoted "false" is truthy in an `if`; it must disable the wait too.
    Case(
        "mcp-mesh-registry",
        'registry.database.waitForDatabase="false" (string) drops the init container',
        {"registry": {"database": {"waitForDatabase": "false"}}},
        forbids_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-registry",
        "registry.database.waitForDatabase=null keeps the default",
        {"registry": {"database": {"waitForDatabase": None}}},
        requires_init_container="wait-for-db",
    ),
    # The `initContainers:` header used to be emitted only with wait-for-db,
    # so user initContainers without it rendered invalid YAML — previously
    # reachable only on sqlite, and on any database once false was honoured.
    Case(
        "mcp-mesh-registry",
        "user initContainers still render with waitForDatabase=false",
        {
            "registry": {"database": {"waitForDatabase": False}},
            "initContainers": [{"name": "mine", "image": "busybox:1.35"}],
        },
        requires_init_container="mine",
        forbids_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-registry",
        "user initContainers render on sqlite",
        {
            "registry": {"database": {"type": "sqlite"}},
            "initContainers": [{"name": "mine", "image": "busybox:1.35"}],
        },
        requires_init_container="mine",
        forbids_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-registry",
        "user initContainers render alongside wait-for-db",
        {"initContainers": [{"name": "mine", "image": "busybox:1.35"}]},
        requires_init_container="mine",
    ),
    # The umbrella sets waitForDatabase: true explicitly, so this is the
    # path an operator actually takes.
    Case(
        "mcp-mesh-core",
        "waitForDatabase=false through the umbrella drops the init container",
        {"mcp-mesh-registry": {"registry": {"database": {"waitForDatabase": False}}}},
        forbids_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-core",
        "...and the umbrella default keeps it",
        {},
        requires_init_container="wait-for-db",
    ),
    # --- mcp-mesh-registry: removed token auth (#1573) -------------------
    # The registry has no token auth. These keys mounted an AUTH_TOKENS var
    # nothing reads, so enabling them looked protected and was not.
    Case(
        "mcp-mesh-registry",
        "registry.security.auth.enabled=true protects nothing",
        {"registry": {"security": {"auth": {"enabled": True}}}},
        expect_fail=f"registry.security.auth.enabled {REGISTRY_AUTH_REMOVED}",
    ),
    Case(
        "mcp-mesh-registry",
        "registry.security.auth.tokens protects nothing",
        {"registry": {"security": {"auth": {"tokens": ["s3cret"]}}}},
        expect_fail=f"registry.security.auth.tokens {REGISTRY_AUTH_REMOVED}",
    ),
    Case(
        "mcp-mesh-registry",
        "registry.security.auth.existingSecret protects nothing",
        {"registry": {"security": {"auth": {"existingSecret": "registry-tokens"}}}},
        expect_fail=f"registry.security.auth.existingSecret {REGISTRY_AUTH_REMOVED}",
    ),
    Case(
        "mcp-mesh-registry",
        "the shipped registry.security.auth defaults are grandfathered",
        {"registry": {"security": {"auth": dict(SHIPPED_REGISTRY_AUTH)}}},
        forbids_env=DEAD_REGISTRY_ENV,
    ),
    Case(
        "mcp-mesh-registry",
        "null registry.security.auth values carry no intent",
        {"registry": {"security": {"auth": {"existingSecret": None, "tokens": None}}}},
    ),
    Case(
        "mcp-mesh-core",
        "registry auth through the umbrella still fails",
        {"mcp-mesh-registry": {"registry": {"security": {"auth": {"enabled": True}}}}},
        expect_fail=f"registry.security.auth.enabled {REGISTRY_AUTH_REMOVED}",
    ),
    # --- mcp-mesh-ingress (standalone chart) ------------------------------
    Case(
        "mcp-mesh-ingress",
        "neither ingress pattern enabled",
        {
            "patterns": {
                "hostBased": {"enabled": False},
                "pathBased": {"enabled": False},
            }
        },
        expect_fail="At least one ingress pattern",
    ),
    Case(
        "mcp-mesh-ingress",
        "a host-based ingress",
        {
            "patterns": {
                "hostBased": {"enabled": True},
                "pathBased": {"enabled": False},
            }
        },
    ),
    # --- #1574: registry probes are values, defaults unchanged -----------
    Case(
        "mcp-mesh-registry",
        "the default probes are the ones deployment.yaml used to hard-code",
        {},
        probe_specs=REGISTRY_PROBES_BEFORE_1574,
    ),
    Case(
        "mcp-mesh-registry",
        "a probe value is honoured",
        {"livenessProbe": {"initialDelaySeconds": 60}},
        probe_specs={
            "livenessProbe": {
                **REGISTRY_PROBES_BEFORE_1574["livenessProbe"],
                "initialDelaySeconds": 60,
            }
        },
    ),
    Case(
        "mcp-mesh-registry",
        "an exec handler replaces httpGet",
        {"readinessProbe": {"httpGet": None, "exec": {"command": ["true"]}}},
        probe_specs={
            "readinessProbe": {
                **{
                    k: v
                    for k, v in REGISTRY_PROBES_BEFORE_1574["readinessProbe"].items()
                    if k != "httpGet"
                },
                "exec": {"command": ["true"]},
            }
        },
    ),
    Case(
        "mcp-mesh-registry",
        "a partial probe with no handler keeps the default handler",
        # What `--reuse-values` from 3.7 plus `--set
        # startupProbe.failureThreshold=60` hands the template: no default
        # startupProbe to merge with, so no httpGet (null drops it here).
        {"startupProbe": {"failureThreshold": 60, "httpGet": None}},
        probe_specs={
            "startupProbe": {
                **REGISTRY_PROBES_BEFORE_1574["startupProbe"],
                "failureThreshold": 60,
            }
        },
    ),
    Case(
        "mcp-mesh-registry",
        "--reuse-values from 3.7 (no startupProbe, the never-read liveness) keeps the probes",
        # `helm upgrade --reuse-values` renders with the OLD chart's values:
        # no startupProbe key (null here is the same thing after Helm's
        # merge) and the livenessProbe values.yaml declared but nothing read.
        {
            "startupProbe": None,
            "livenessProbe": {
                "httpGet": {"path": "/health", "port": "http"},
                "initialDelaySeconds": 10,
                "periodSeconds": 10,
                "timeoutSeconds": 5,
                "failureThreshold": 3,
            },
        },
        probe_specs=REGISTRY_PROBES_BEFORE_1574,
    ),
    Case(
        "mcp-mesh-core",
        "the umbrella renders the same registry probes",
        # Every other workload off (postgres via an external database), so
        # the registry is the only container the probe check sees.
        {
            "postgres": {"enabled": False},
            "redis": {"enabled": False},
            "grafana": {"enabled": False},
            "tempo": {"enabled": False},
            "global": {"postgres": {"host": "db.example.com", "existingSecret": "pg"}},
        },
        probe_specs=REGISTRY_PROBES_BEFORE_1574,
    ),
    # --- #1574: registry database type and sqlite DATABASE_URL -----------
    Case(
        "mcp-mesh-registry",
        "sqlite at /data renders no DATABASE_URL, so the image's own file applies",
        {"registry": {"database": {"type": "sqlite"}}},
        forbids_env=("DATABASE_URL",),
    ),
    Case(
        "mcp-mesh-registry",
        "sqlite at /data leaves a user-supplied DATABASE_URL alone",
        {
            "registry": {"database": {"type": "sqlite"}},
            "env": [{"name": "DATABASE_URL", "value": "/data/custom.db"}],
        },
        env_values={"DATABASE_URL": "/data/custom.db"},
        env_unique=("DATABASE_URL",),
    ),
    Case(
        "mcp-mesh-registry",
        "registry.database.path was never applied",
        {"registry": {"database": {"type": "sqlite", "path": "/data/mesh.db"}}},
        expect_fail="registry.database.path was never applied and has been removed",
    ),
    Case(
        "mcp-mesh-registry",
        "the shipped registry.database.path is grandfathered and changes nothing",
        {"registry": {"database": {"type": "sqlite", "path": "/data/registry.db"}}},
        forbids_env=("DATABASE_URL",),
    ),
    Case(
        "mcp-mesh-registry",
        "a moved sqlite volume gets DATABASE_URL on it",
        {
            "registry": {"database": {"type": "sqlite"}},
            "persistence": {"mountPath": "/var/lib/registry"},
        },
        env_values={"DATABASE_URL": "/var/lib/registry/mcp_mesh_registry.db"},
    ),
    Case(
        "mcp-mesh-registry",
        "a moved sqlite volume keeps a user-supplied DATABASE_URL, declared once",
        {
            "registry": {"database": {"type": "sqlite"}},
            "persistence": {"mountPath": "/var/lib/registry"},
            "env": [{"name": "DATABASE_URL", "value": "/var/lib/registry/mine.db"}],
        },
        env_values={"DATABASE_URL": "/var/lib/registry/mine.db"},
        env_unique=("DATABASE_URL",),
    ),
    Case(
        "mcp-mesh-registry",
        "mysql has no driver in the registry",
        {"registry": {"database": {"type": "mysql"}}},
        expect_fail='registry.database.type="mysql" is not supported',
    ),
    # --- #1574: registry adminTLS ------------------------------------------
    Case(
        "mcp-mesh-registry",
        "adminTLS without adminPort",
        {"registry": {"security": {"adminTLS": True}}},
        expect_fail="adminTLS applies only to a separate admin listener",
    ),
    Case(
        "mcp-mesh-registry",
        "adminTLS without registry TLS",
        {"registry": {"security": {"adminTLS": True, "adminPort": 9443}}},
        expect_fail="requires registry.security.tls.enabled=true",
    ),
    Case(
        "mcp-mesh-registry",
        "adminTLS with tls.mode off (the default)",
        {
            "registry": {
                "security": {
                    "adminTLS": True,
                    "adminPort": 9443,
                    "tls": {"enabled": True, "secretName": "reg-tls"},
                }
            }
        },
        expect_fail="adminTLS needs registry.security.tls.mode auto or strict",
    ),
    Case(
        "mcp-mesh-registry",
        "adminTLS renders MCP_MESH_ADMIN_TLS",
        {
            "registry": {
                "security": {
                    "adminTLS": True,
                    "adminPort": 9443,
                    "tls": {"enabled": True, "mode": "strict", "secretName": "reg-tls"},
                    "trust": {"backend": "k8s-secrets"},
                }
            }
        },
        config_data={"MCP_MESH_ADMIN_TLS": "true", "MCP_MESH_ADMIN_PORT": "9443"},
    ),
    Case(
        "mcp-mesh-registry",
        'adminTLS "false" leaves the admin port as it was',
        {"registry": {"security": {"adminTLS": "false", "adminPort": 9443}}},
        config_data={"MCP_MESH_ADMIN_PORT": "9443"},
        forbids_env=("MCP_MESH_ADMIN_TLS",),
    ),
    # --- #1574: removed registry keys --------------------------------------
    *[
        Case(
            "mcp-mesh-registry",
            f"{key} was never read",
            values,
            expect_fail=f"{key} was never read by any template and has been removed",
        )
        for key, values in REMOVED_REGISTRY_KEYS
    ],
    Case(
        "mcp-mesh-registry",
        "the removed keys at their shipped defaults are grandfathered",
        SHIPPED_REMOVED_REGISTRY_KEYS,
    ),
    Case(
        "mcp-mesh-registry",
        "null on a removed key renders (Helm drops it before the guard sees it)",
        {"workloadType": None, "registry": {"healthCheck": {"interval": None}}},
    ),
    Case(
        "mcp-mesh-core",
        "a removed registry key through the umbrella still fails",
        {"mcp-mesh-registry": {"workloadType": "StatefulSet"}},
        expect_fail="workloadType was never read by any template",
    ),
    # --- #1574: umbrella removed keys and the external-database guard -------
    Case(
        "mcp-mesh-core",
        "podDisruptionBudgets.enabled was removed",
        {"podDisruptionBudgets": {"enabled": True}},
        expect_fail="podDisruptionBudgets.enabled was never consumed",
    ),
    Case(
        "mcp-mesh-core",
        "podDisruptionBudgets.enabled: false (the old default) is tolerated",
        {"podDisruptionBudgets": {"enabled": False}},
    ),
    Case(
        "mcp-mesh-core",
        "postgres off still pointing at this release's bundled host",
        {
            "postgres": {"enabled": False},
            "global": {"postgres": {"host": "render-matrix-mcp-mesh-postgres"}},
        },
        expect_fail="the registry still connects to it (render-matrix-mcp-mesh-postgres)",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with nothing configured has no database",
        {"postgres": {"enabled": False}},
        expect_fail="the registry still connects to it (mcp-core-mcp-mesh-postgres)",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with an external host but the generated credential",
        {"postgres": {"enabled": False}, "global": {"postgres": {"host": "db.example.com"}}},
        expect_fail="takes its password from the bundled chart's generated Secret",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with an external database renders",
        {
            "postgres": {"enabled": False},
            "global": {"postgres": {"host": "db.example.com", "existingSecret": "pg"}},
        },
        requires_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off checks the UI too",
        {
            "postgres": {"enabled": False},
            "ui": {"enabled": True},
            "mcp-mesh-registry": {
                "registry": {"database": {"host": "db.example.com", "password": "x"}}
            },
        },
        expect_fail="but the UI still connects to it",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with a sqlite registry needs no external database",
        {
            "postgres": {"enabled": False},
            "mcp-mesh-registry": {"registry": {"database": {"type": "sqlite"}}},
        },
        forbids_env=("DATABASE_URL",),
        forbids_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-core",
        "grafana's tempo datasource follows the release name",
        {},
        config_contains={"datasources.yaml": "url: http://render-matrix-mcp-mesh-tempo:3200"},
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with a full DSN secret and wait-for-db off renders",
        {
            "postgres": {"enabled": False},
            "ui": {"enabled": True},
            "global": {"postgres": {"existingSecret": "pg", "existingSecretUrlKey": "dsn"}},
            "mcp-mesh-registry": {"registry": {"database": {"waitForDatabase": False}}},
        },
        forbids_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with a full DSN secret but wait-for-db aimed at the bundled host",
        {
            "postgres": {"enabled": False},
            "global": {"postgres": {"existingSecret": "pg", "existingSecretUrlKey": "dsn"}},
        },
        expect_fail="its wait-for-db init container still waits on mcp-core-mcp-mesh-postgres",
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with a full DSN secret and wait-for-db on the real host renders",
        {
            "postgres": {"enabled": False},
            "global": {
                "postgres": {
                    "host": "db.example.com",
                    "existingSecret": "pg",
                    "existingSecretUrlKey": "dsn",
                }
            },
        },
        requires_init_container="wait-for-db",
    ),
    Case(
        "mcp-mesh-core",
        "global.coreReleaseName naming this release (a user's own umbrella) renders",
        {"global": {"coreReleaseName": "render-matrix"}},
    ),
    Case(
        "mcp-mesh-ingress",
        "an umbrella-style install routes once coreReleaseName names the release",
        {"global": {"coreReleaseName": "render-matrix"}, "core": {"ui": {"enabled": True}}},
        routes_to=(
            (
                "mcp-mesh-core",
                "render-matrix",
                ("--set", "ui.enabled=true", "--set", "global.coreReleaseName=render-matrix"),
            ),
        ),
    ),
    Case(
        "mcp-mesh-core",
        "postgres off with no host at any layer falls back to a bundled name",
        {
            "postgres": {"enabled": False},
            "global": {"postgres": {"host": "", "password": "x"}},
        },
        expect_fail="the registry still connects to it (mcp-mesh-postgres)",
    ),
    # --- #1633 review: registry probes under TLS ---------------------------
    Case(
        "mcp-mesh-registry",
        "TLS auto: probes speak HTTPS to the HTTPS-only port",
        {
            "registry": {
                "security": {
                    "tls": {"enabled": True, "mode": "auto", "secretName": "reg-tls"},
                    "trust": {"backend": "k8s-secrets"},
                }
            }
        },
        probe_specs={
            name: {**spec, "httpGet": {**spec["httpGet"], "scheme": "HTTPS"}}
            for name, spec in REGISTRY_PROBES_BEFORE_1574.items()
        },
    ),
    Case(
        "mcp-mesh-registry",
        "TLS strict: certless probes would get 403, so they check the socket",
        {
            "registry": {
                "security": {
                    "tls": {"enabled": True, "mode": "strict", "secretName": "reg-tls"},
                    "trust": {"backend": "k8s-secrets"},
                }
            }
        },
        probe_specs={
            name: {
                **{k: v for k, v in spec.items() if k != "httpGet"},
                "tcpSocket": {"port": "http"},
            }
            for name, spec in REGISTRY_PROBES_BEFORE_1574.items()
        },
    ),
    Case(
        "mcp-mesh-registry",
        "TLS strict leaves a probe with an explicit scheme alone",
        {
            "registry": {
                "security": {
                    "tls": {"enabled": True, "mode": "strict", "secretName": "reg-tls"},
                    "trust": {"backend": "k8s-secrets"},
                }
            },
            "livenessProbe": {"httpGet": {"scheme": "HTTP"}},
        },
        probe_specs={
            "livenessProbe": {
                **REGISTRY_PROBES_BEFORE_1574["livenessProbe"],
                "httpGet": {"path": "/health", "port": "http", "scheme": "HTTP"},
            }
        },
    ),
    Case(
        "mcp-mesh-registry",
        "a moved sqlite volume with envFrom renders no DATABASE_URL over it",
        {
            "registry": {"database": {"type": "sqlite"}},
            "persistence": {"mountPath": "/var/lib/registry"},
            "envFrom": [{"secretRef": {"name": "registry-db"}}],
        },
        forbids_env=("DATABASE_URL",),
    ),
    # --- #1633 review: derived names follow the component fullname rule ----
    Case(
        "mcp-mesh-ingress",
        "a core release named after a component chart routes to its Service",
        {"global": {"coreReleaseName": "mcp-mesh-registry"}},
        routes_to=(("mcp-mesh-core", "mcp-mesh-registry", ()),),
    ),
    Case(
        "mcp-mesh-ingress",
        "a templated agent service is rendered with tpl",
        {
            "agents": [
                {"name": "hello", "service": "{{ .Release.Name }}-mcp-mesh-agent"}
            ]
        },
        routes_to=(CORE_AT_MCP_CORE, ("mcp-mesh-agent", "render-matrix", ())),
    ),
    Case(
        "mcp-mesh-grafana",
        "a release named after the tempo chart uses the tempo chart's fullname",
        {"grafana": {"config": {"adminPassword": "x"}}},
        release="mcp-mesh-tempo",
        config_contains={"datasources.yaml": "url: http://mcp-mesh-tempo:3200"},
    ),
    # --- #1574: agent.http.enabled off makes a valid non-HTTP agent --------
    Case(
        "mcp-mesh-agent",
        "http off drops the Service, port and probes",
        {
            "agent": {"http": {"enabled": False}},
            "ingress": {"enabled": True},
            "serviceMonitor": {"enabled": True},
        },
        config_data={"MCP_MESH_HTTP_ENABLED": "false"},
        probe_specs=NO_PROBES,
        forbids_kinds=("Service", "Ingress", "ServiceMonitor"),
    ),
    Case(
        "mcp-mesh-agent",
        'http "false" (quoted) is off everywhere, not just in the env',
        {
            "agent": {"http": {"enabled": "false"}},
            "ingress": {"enabled": True},
            "serviceMonitor": {"enabled": True},
        },
        config_data={"MCP_MESH_HTTP_ENABLED": "false"},
        probe_specs=NO_PROBES,
        forbids_kinds=("Service", "Ingress", "ServiceMonitor"),
    ),
    Case(
        "mcp-mesh-agent",
        "http off keeps a probe that does not use the http port",
        {
            "agent": {"http": {"enabled": False}},
            "livenessProbe": {"httpGet": None, "exec": {"command": ["cat", "/tmp/alive"]}},
        },
        probe_specs={
            "startupProbe": None,
            "readinessProbe": None,
            "livenessProbe": {
                "exec": {"command": ["cat", "/tmp/alive"]},
                "initialDelaySeconds": 15,
                "periodSeconds": 10,
                "timeoutSeconds": 5,
                "failureThreshold": 3,
            },
        },
    ),
    Case(
        "mcp-mesh-agent",
        "http null means on, everywhere",
        {"agent": {"http": {"enabled": None}}, "ingress": {"enabled": True}},
        config_data={"MCP_MESH_HTTP_ENABLED": "true"},
        requires_kind="Ingress",
        probe_paths={
            "startupProbe": "/startupz",
            "livenessProbe": "/livez",
            "readinessProbe": "/ready",
        },
    ),
    # --- #1574: removed agent keys -----------------------------------------
    *[
        Case(
            "mcp-mesh-agent",
            f"{key} was never read",
            values,
            expect_fail=(
                f"{key} has been removed"
                if key == "podSecurityPolicy.enabled"
                else f"{key} was never read by any template and has been removed"
            ),
        )
        for key, values in REMOVED_AGENT_KEYS
    ],
    Case(
        "mcp-mesh-agent",
        "the removed agent keys at their shipped defaults are grandfathered",
        SHIPPED_REMOVED_AGENT_KEYS,
    ),
    # --- #1574: ingress routes to what core and the agents actually render --
    Case(
        "mcp-mesh-ingress",
        "the default ingress routes to the registry of a core installed as mcp-core",
        {},
        routes_to=(CORE_AT_MCP_CORE,),
    ),
    Case(
        "mcp-mesh-ingress",
        "README Pattern 1 (core + hello-world agent + ingress) routes",
        {
            "agents": [{"name": "hello-world"}],
            "core": {"ui": {"enabled": True}, "grafana": {"enabled": True}},
            "patterns": {"pathBased": {"enabled": True}},
        },
        routes_to=(CORE_AT_MCP_CORE, AGENT_HELLO_WORLD),
    ),
    Case(
        "mcp-mesh-ingress",
        "the old shipped {{ .Release.Name }} service names route to core",
        {
            "core": {
                "registry": {"service": "{{ .Release.Name }}-mcp-mesh-registry"},
                "ui": {"enabled": True, "service": "{{ .Release.Name }}-mcp-mesh-ui"},
            }
        },
        routes_to=(CORE_AT_MCP_CORE,),
    ),
    Case(
        "mcp-mesh-ingress",
        "global.serviceNamespace never produced a valid backend",
        {"global": {"serviceNamespace": "mcp-mesh"}},
        expect_fail="global.serviceNamespace has been removed",
    ),
    Case(
        "mcp-mesh-ingress",
        "the ingress chart has no pods to schedule",
        {"nodeSelector": {"role": "edge"}},
        expect_fail="nodeSelector was never read by any template",
    ),
    Case(
        "mcp-mesh-ingress",
        "an agent entry needs a name",
        {"agents": [{"port": 8080}]},
        expect_fail="agents[0] needs a name",
    ),
    # --- #1574: standalone grafana tempo datasource -----------------------
    Case(
        "mcp-mesh-grafana",
        "the tempo datasource is a real service name, not a template literal",
        {"grafana": {"config": {"adminPassword": "x"}}},
        config_contains={"datasources.yaml": "url: http://render-matrix-mcp-mesh-tempo:3200"},
    ),
    Case(
        "mcp-mesh-grafana",
        "the old shipped include literal is treated as unset",
        {
            "grafana": {
                "config": {"adminPassword": "x"},
                "datasources": {
                    "tempo": {"url": 'http://{{ include "mcp-mesh-core.fullname" . }}-tempo:3200'}
                },
            }
        },
        config_contains={"datasources.yaml": "url: http://render-matrix-mcp-mesh-tempo:3200"},
    ),
    Case(
        "mcp-mesh-grafana",
        "a templated tempo URL is rendered",
        {
            "grafana": {
                "config": {"adminPassword": "x"},
                "datasources": {
                    "tempo": {"url": "http://{{ .Release.Name }}-tempo.observability:3200"}
                },
            }
        },
        config_contains={
            "datasources.yaml": "url: http://render-matrix-tempo.observability:3200"
        },
    ),
]


def run_case(case: Case, values_file: Path) -> str | None:
    """Return None when the case behaved as declared, else a failure reason."""
    values_file.write_text(yaml.safe_dump(case.values))
    result = subprocess.run(
        [
            "helm",
            "template",
            case.release,
            str(HELM_DIR / case.chart),
            "--values",
            str(values_file),
            *case.extra_args,
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr

    if case.expect_fail is None:
        if result.returncode != 0:
            return f"expected a clean render, helm template failed:\n{_indent(output)}"
        if not result.stdout.strip():
            return "expected a clean render, helm template produced no manifests"
        kinds = _rendered_kinds(result.stdout)
        if case.requires_kind and case.requires_kind not in kinds:
            return f"the render contains no {case.requires_kind} object"
        for kind in (case.forbids_kind, *case.forbids_kinds):
            if kind and kind in kinds:
                return (
                    f"the render contains a {kind} object, which these values "
                    "must not produce"
                )
        if case.probe_paths:
            reason = _check_probe_paths(result.stdout, case.probe_paths)
            if reason:
                return reason
        if case.probe_specs:
            reason = _check_probe_specs(result.stdout, case.probe_specs)
            if reason:
                return reason
        if case.routes_to:
            reason = _check_routes(result.stdout, case.routes_to)
            if reason:
                return reason
        return _check_config(result.stdout, case)

    if result.returncode == 0:
        return (
            f"expected the render to fail with {case.expect_fail!r}, "
            "but it succeeded — the guard is gone or no longer reachable"
        )
    if case.expect_fail not in output:
        return (
            f"render failed, but not with {case.expect_fail!r} — a different "
            f"guard (or a template error) fired:\n{_indent(output)}"
        )
    return None


def _check_probe_paths(manifests: str, expected: dict[str, str]) -> str | None:
    """Assert every workload container's probes use the declared httpGet paths.

    Also rejects two declared probes sharing one path regardless of what was
    declared — the invariant behind issues #1467/#1468 and RFC #1502 is that
    startup (restart before serving), liveness (restart) and readiness (stop
    routing) are three different failure actions and can never be one signal.
    Matching three distinct literals already implies this today; asserting it
    separately is what keeps the claim true if the literals are ever edited.
    """
    containers = [
        container
        for doc in yaml.safe_load_all(manifests)
        if isinstance(doc, dict)
        and doc.get("kind") in {"Deployment", "StatefulSet", "DaemonSet"}
        for container in doc["spec"]["template"]["spec"].get("containers", [])
    ]
    if not containers:
        return "the render contains no workload containers to probe"

    for container in containers:
        for probe, want in expected.items():
            spec = container.get(probe)
            if not spec:
                return f"container {container['name']!r} has no {probe}"
            got = spec.get("httpGet", {}).get("path")
            if got != want:
                return (
                    f"container {container['name']!r} {probe} probes {got!r}, "
                    f"expected {want!r}"
                )
        liveness = container.get("livenessProbe", {}).get("httpGet", {}).get("path")
        readiness = container.get("readinessProbe", {}).get("httpGet", {}).get("path")
        if liveness is not None and liveness == readiness:
            return (
                f"container {container['name']!r} probes liveness and readiness "
                f"at the same path {liveness!r} — a dependency outage would "
                "restart the pod instead of only taking it out of rotation"
            )
        seen: dict[str, str] = {}
        for probe in expected:
            path = container.get(probe, {}).get("httpGet", {}).get("path")
            if path is None:
                continue
            if path in seen:
                return (
                    f"container {container['name']!r} probes {seen[path]} and "
                    f"{probe} at the same path {path!r} — each probe has its "
                    "own failure action and needs its own endpoint"
                )
            seen[path] = probe
    return None


def _workload_containers(manifests: str) -> list[dict]:
    return [
        container
        for doc in yaml.safe_load_all(manifests)
        if isinstance(doc, dict)
        and doc.get("kind") in {"Deployment", "StatefulSet", "DaemonSet"}
        for container in doc["spec"]["template"]["spec"].get("containers", [])
    ]


def _check_probe_specs(manifests: str, expected: dict[str, dict | None]) -> str | None:
    """Assert each workload container's probes equal the declared specs."""
    containers = _workload_containers(manifests)
    if not containers:
        return "the render contains no workload containers to probe"
    for container in containers:
        for probe, want in expected.items():
            got = container.get(probe)
            if got != want:
                return f"container {container['name']!r} {probe} is {got!r}, expected {want!r}"
    return None


def _check_routes(
    manifests: str, targets: tuple[tuple[str, str, tuple[str, ...]], ...]
) -> str | None:
    """Assert every Ingress backend is a Service the target charts render."""
    services: set[tuple[str, int]] = set()
    for chart, release, args in targets:
        build_dependencies(chart)
        result = subprocess.run(
            ["helm", "template", release, str(HELM_DIR / chart), *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"routing target {chart} ({release}) failed to render:\n{_indent(result.stderr)}"
        for doc in yaml.safe_load_all(result.stdout):
            if isinstance(doc, dict) and doc.get("kind") == "Service":
                for port in doc["spec"].get("ports", []):
                    services.add((doc["metadata"]["name"], int(port["port"])))
    backends = [
        (path["backend"]["service"]["name"], int(path["backend"]["service"]["port"]["number"]))
        for doc in yaml.safe_load_all(manifests)
        if isinstance(doc, dict) and doc.get("kind") == "Ingress"
        for rule in doc["spec"].get("rules", [])
        for path in rule["http"]["paths"]
    ]
    if not backends:
        return "the render contains no Ingress backends"
    for name, port in backends:
        if (name, port) not in services:
            return (
                f"an Ingress routes to Service {name}:{port}, which "
                f"{', '.join(f'{c} ({r})' for c, r, _ in targets)} do not render "
                f"(they render {sorted(services)})"
            )
    return None


def _check_config(manifests: str, case: Case) -> str | None:
    """Assert the ConfigMap values, forbidden env names and init containers."""
    docs = [d for d in yaml.safe_load_all(manifests) if isinstance(d, dict)]
    config: dict[str, list[str]] = {}
    for doc in docs:
        if doc.get("kind") == "ConfigMap":
            for key, val in (doc.get("data") or {}).items():
                config.setdefault(key, []).append(str(val))

    pod_specs = [
        doc["spec"]["template"]["spec"]
        for doc in docs
        if doc.get("kind") in {"Deployment", "StatefulSet", "DaemonSet"}
    ]
    env_names: set[str] = set()
    init_names: set[str] = set()
    for spec in pod_specs:
        for container in spec.get("initContainers") or []:
            init_names.add(container.get("name"))
        for container in (spec.get("containers") or []) + (
            spec.get("initContainers") or []
        ):
            env_names.update(e.get("name") for e in container.get("env") or [])

    for key, want in (case.config_data or {}).items():
        got = config.get(key)
        if not got:
            return f"no rendered ConfigMap carries {key}"
        if want not in got:
            return f"{key} renders {got}, expected {want!r}"
    for key, want in (case.config_contains or {}).items():
        got = config.get(key)
        if not got:
            return f"no rendered ConfigMap carries {key}"
        if not any(want in value for value in got):
            return f"{key} does not contain {want!r}:\n{_indent(got[0])}"
    env_values: dict[str, list[str]] = {}
    for spec in pod_specs:
        for container in spec.get("containers") or []:
            for entry in container.get("env") or []:
                if "value" in entry:
                    env_values.setdefault(entry["name"], []).append(str(entry["value"]))
    for spec in pod_specs:
        for container in spec.get("containers") or []:
            names = [e.get("name") for e in container.get("env") or []]
            for name in case.env_unique:
                if names.count(name) > 1:
                    return f"container {container['name']!r} declares {name} {names.count(name)} times"
    for name, want in (case.env_values or {}).items():
        got = env_values.get(name)
        if not got:
            return f"no workload container sets {name}"
        if want not in got:
            return f"{name} renders {got}, expected {want!r}"
    for name in case.forbids_env:
        if name in config:
            return f"a ConfigMap still injects {name}, which no runtime reads"
        if name in env_names:
            return f"a container still injects {name}, which no runtime reads"
    if case.requires_init_container and case.requires_init_container not in init_names:
        return f"no workload declares the {case.requires_init_container!r} init container"
    if case.forbids_init_container and case.forbids_init_container in init_names:
        return (
            f"a workload still declares the {case.forbids_init_container!r} "
            "init container"
        )
    return None


def _rendered_kinds(manifests: str) -> set[str]:
    return {
        doc["kind"]
        for doc in yaml.safe_load_all(manifests)
        if isinstance(doc, dict) and "kind" in doc
    }


def _indent(text: str) -> str:
    lines = text.strip().splitlines()
    return "\n".join(f"      {line}" for line in lines[:12])


def main() -> int:
    for chart in sorted({c.chart for c in CASES}):
        build_dependencies(chart)

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        values_file = Path(tmp) / "values.yaml"
        for case in CASES:
            reason = run_case(case, values_file)
            verdict = "fails" if case.expect_fail else "renders"
            if reason is None:
                print(f"OK   {case.chart}: {case.name} ({verdict})")
            else:
                failures += 1
                print(f"FAIL {case.chart}: {case.name} ({verdict})")
                print(f"  -> {reason}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} render cases behaved as declared")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
