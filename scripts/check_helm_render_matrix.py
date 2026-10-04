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
        expect_fail="global.coreReleaseName was documentation-only",
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
]


def run_case(case: Case, values_file: Path) -> str | None:
    """Return None when the case behaved as declared, else a failure reason."""
    values_file.write_text(yaml.safe_dump(case.values))
    result = subprocess.run(
        [
            "helm",
            "template",
            "render-matrix",
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
        if case.forbids_kind and case.forbids_kind in kinds:
            return (
                f"the render contains a {case.forbids_kind} object, which "
                "these values must not produce"
            )
        if case.probe_paths:
            reason = _check_probe_paths(result.stdout, case.probe_paths)
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
