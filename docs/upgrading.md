---
title: Upgrading a Live Mesh
description: Upgrade order, version-skew guarantees, schema migrations, and in-flight job safety for a running MCP Mesh
---

# Upgrading a Live Mesh

Order of operations, version-skew guarantees, schema migrations, and in-flight
job safety for upgrading a mesh that is already serving traffic. For local
development you can restart freely; this page is about upgrading a running
deployment without dropping in-flight work.

!!! danger "Upgrade order for the Helm charts: 3.3.x → 3.4.x → 3.5.0"

    **Do not upgrade the `mcp-mesh-core` chart from 3.3.x straight to 3.5.0.**
    Chart 3.5.0 changes `namespaceCreate` to default `false`, which drops the
    release's `Namespace` object from the rendered manifest — and Helm
    *deletes* a resource that leaves the manifest, cascading to every agent,
    Service, Secret and PVC in the namespace. What makes that removal safe is
    `helm.sh/resource-policy: keep` on the live `Namespace`, and chart 3.4.0
    is the first version that puts it there.

    - **On chart 3.4.x already:** nothing to do — the annotation is on the
      live namespace, so 3.5.0 removes the object without deleting anything.
    - **On chart 3.3.x or older:** upgrade to the latest 3.4.x first, verify
      with `kubectl get ns <ns> -o jsonpath='{.metadata.annotations}'`, then
      upgrade to 3.5.0. To jump in one step instead, pin
      `--set namespaceCreate=true` for that upgrade, verify the annotation,
      and drop the pin on a second upgrade.

    `--reuse-values` does **not** protect you: it replays the values you
    supplied, and a release that simply took the old default has nothing to
    replay. Details in
    [Namespace handling](https://github.com/dhyansraj/mcp-mesh/blob/main/helm/mcp-mesh-core/README.md#existing-releases-upgrading-past-the-default-flip).

!!! warning "Source migration required for 3.4.0 (Java and TypeScript)"

    3.4.0 aligns every dependency-injection site on positional binding. Java
    `@MeshRoute` / `@MeshA2A` and TypeScript `mesh.route` / `mesh.a2a.mount`
    changed how declared dependencies reach handler parameters. Python is
    unchanged, and Java `@MeshTool` and TypeScript `addTool` were already
    positional — but `@MeshInject` is now honoured on `@MeshTool` parameters,
    where it was previously ignored, so a value that disagrees with its
    parameter's position fails at boot. Nothing on the wire
    changed, so no coordinated rollout is needed — but handlers need a source
    edit. Do not filter by dependency count: every TypeScript handler still
    taking a capability-keyed object converts whatever it declares, and a Java
    handler with one dependency is exempt only when its `@MeshInject` already
    names that capability, or carries none. See
    [Migrating to positional DI](migration/3.4-positional-di.md).

## Recommended order

Upgrade the **registry first, then the agents**.

The registry runs its schema migration at startup (see
[Schema migrations](#schema-migrations)), so bringing it up first means the new
columns exist before any newer-SDK agent tries to use them. The compatibility
contract (see [Version skew](#version-skew)) holds in both directions, so agents
can trail the registry by a version with no hard failure — but registry-first is
the order with the fewest moving parts: migrate once, then roll agents at your
own pace.

## Version skew

A mixed-version mesh always converges to the **older side's semantics** — there
is no hard failure when registry and SDK versions differ. This is the
compatibility contract:

- **Newer registry, older-SDK agents.** Older agents post epoch-less job
  deltas. The registry validates these **owner-only, with no fencing** — the
  legacy path. Event reads without identity parameters are served
  **anonymously** (unchanged). When an agent sends no identity headers, the
  registry's identity accessors read null and it falls back to legacy handling.
- **Older registry, newer-SDK agents.** The newer SDK's epoch and identity
  headers are unknown fields to an older registry and are ignored — so the same
  legacy, owner-only behavior results.

In both directions the behavior degrades to the pre-fencing legacy path by
design. The only thing you lose in a skewed mesh is claim-epoch fencing
(dual-ownership protection) — which is exactly why an upgrade should drain
in-flight jobs rather than rely on fencing across the restart (see
[In-flight job safety](#in-flight-job-safety)).

## Schema migrations

The registry runs **ent automigrate at startup** — it reconciles the database
schema against the compiled models on every boot. New releases add columns;
automigrate applies them automatically. **There is no manual migration step.**

Forward upgrade (new registry against an existing database) is purely
**additive** — new columns are created, existing data is untouched.

!!! warning "Rollback caveat"
    Automigrate runs with drop-column and drop-index enabled. If you downgrade
    the registry binary, its older schema no longer declares the newer columns,
    so the startup migration will **drop them**. The older binary operates
    correctly afterward (it never referenced those columns), but the drop is
    **destructive** — any state held in the newer columns (for example the
    claim-epoch/lease bookkeeping for in-flight jobs) is lost and does not come
    back if you later re-upgrade. Treat a registry downgrade as
    forward-only-safe: fine for the running version, not a non-destructive
    rollback.

## In-flight job safety

Job rows persist across a registry restart, but **leases cannot renew while the
registry is down**. During downtime:

- job completions retry against the unreachable registry,
- event-gated (`input_required`) jobs **freeze** rather than drain — their gates
  stall because consumer answers cannot be posted,
- lease clocks keep advancing, so a lease can expire across the outage window.

On restart the orphan/expired-lease **reclaim sweep** races the owner's first
renewing poll: whichever lands first wins. If the sweep reclaims first, a
newer-SDK owner's next delta carries a stale epoch and is fenced
(`claim_superseded`) — safe. But an **older, unfenced SDK** that is re-claimed by
the same instance can produce **dual ownership** (double execution), because
epoch-less deltas get owner-only validation with no fencing.

**Therefore: drain before a live upgrade** rather than pulling the registry out
from under running jobs.

```bash
# 1. Pause new claims; block until every running job releases its owner
meshctl registry drain --wait

# 2. Upgrade / restart the registry (running jobs have finished; queue is safe)

# 3. Resume normal dispatch — queued jobs become claimable again (FIFO)
meshctl registry resume
```

While draining, new claims are paused (queued jobs stay queued — no attempt is
burned), running jobs keep renewing their leases and complete normally, and
submissions are still accepted for after resume. `drain --wait` returns once
`live_claims` reaches zero, and aborts with an error if the registry stops
draining mid-wait (a concurrent `resume` or restart) instead of falsely
reporting the window is safe.

!!! note
    An event-gated job parked in `input_required` counts as a live claim and
    holds the drain open until it is answered or completes. Answer or cancel such
    jobs before draining if you need a bounded window.

!!! warning "Multi-replica (HA) deployments"
    Drain state is **per-replica** and in-memory — it is not shared across
    replicas and a registry restart clears it. In an HA topology a load
    balancer may route each `meshctl registry` command to a different replica,
    so `registry status` can flap and a single `registry drain` pauses only the
    replica that served the request. Before an HA upgrade, **drain every
    replica** by pointing `--registry-url` at each replica's address directly.

!!! note "Separate admin port"
    If the registry runs a dedicated admin port (`MCP_MESH_ADMIN_PORT`), the
    `/admin/drain` endpoints live only on that port. Pass the admin address:
    `meshctl registry drain --registry-url http://<host>:<admin-port>`.

Run `meshctl man registry` for the full drain command reference (`status`,
`--wait-timeout`, `--poll-interval`); the [Registry](concepts/registry.md)
concept page covers the registry's role in the mesh.

## Helm mechanics

For Kubernetes deployments, upgrade **in place** with `helm upgrade` — not by
uninstalling and reinstalling.

```bash
# Preserve the existing release's env/values across the upgrade
helm upgrade <release> <chart> --reuse-values

# Verify the effective values before and after
helm get values <release>
```

- **`--reuse-values`** carries forward the environment configuration set at
  install time so an upgrade does not silently reset it. Confirm with
  `helm get values` that the values you expect are still present.
- **Do not use `helm uninstall` as an upgrade mechanism.** To change the core,
  `helm upgrade` the existing release — uninstalling and reinstalling discards
  the release's history and values along with the running workloads, for no
  benefit.
- **`helm uninstall` is still a legitimate, explicit teardown.** It removes the
  core workloads (registry, PostgreSQL, Redis, and any observability
  components), takes the registry offline with them, and leaves the `Namespace`
  in place (see the next bullet). The registry's contents are
  derived state — agents re-register on their next heartbeat, so the registry
  repopulates itself and the cost is a transient topology gap, not data loss.
  Agents keep serving while it is down: resolved dependencies are never cleared
  on a registry disconnect (a deliberate resilience invariant). What pauses is
  topology detection — discovering new capabilities, re-resolving changed ones,
  and looking up an agent a client has not already resolved. What is *not*
  derived is application data: if your own workloads used the bundled PostgreSQL
  or Redis for their own storage, that data is yours to protect before you tear
  anything down.
- **`helm uninstall` no longer reclaims Grafana's data volume.** The Grafana
  PVC picks up a `"helm.sh/resource-policy": keep` annotation on upgrade, so
  Helm skips it on uninstall — `grafana.persistence.enabled` defaults to `true`,
  and the dashboards, annotations, users, and API keys in `grafana.db` are not
  derived from anything the mesh can replay. Previously that volume was deleted
  along with the release. A reinstall under the same release name adopts the
  existing claim, data intact; reclaim the storage deliberately with
  `kubectl delete pvc <release>-mcp-mesh-grafana-pvc -n <ns>`. This lands on a
  plain `helm upgrade` with no pod restart — the claim never leaves the rendered
  manifest, so it is a metadata-only patch.
- **Tempo's PVC is deleted by this upgrade, and that is intended.**
  `mcp-mesh-tempo.tempo.persistence.enabled` now defaults to `false`, so the
  claim leaves the rendered manifest and Helm reclaims it on the next
  `helm upgrade` — Tempo comes back on an `emptyDir`. What is lost is the
  volume and up to `retention` (default `1h`) of buffered traces: Tempo's
  volume is a rolling buffer under active retention, not durable storage, and
  a live install measured 3.1MB in it after 25 hours of uptime. Nothing else on
  the release is affected and ingestion resumes normally. The default changed
  because the `ReadWriteOnce` claim it required is a real rollout constraint on
  a single-replica Deployment — that is what deadlocked the chart on multi-node
  clusters — paid for minutes of traces. To keep the volume, pin the old value
  in the same upgrade:
  `--set mcp-mesh-tempo.tempo.persistence.enabled=true`; setting it afterward
  provisions a new, empty claim rather than recovering the reclaimed one. This
  is the deliberate opposite of Grafana's treatment above — Grafana's volume
  holds state you authored and nothing can replay.
- **The core chart no longer renders a `Namespace`.** `namespaceCreate` now
  defaults to `false`: `helm install --create-namespace`, `kubectl create
  namespace`, or Argo CD's `CreateNamespace=true` creates the namespace, and
  the release does not own it. The old default could not be installed at all
  on Helm 3, or against any pre-created namespace on any client — Helm writes
  the release secret into the `-n` namespace before applying the manifest, so
  a chart-templated `Namespace` can only re-declare a namespace that already
  exists, which Helm's ownership check rejects. **Read the upgrade-order
  warning at the top of this page before upgrading an existing release**, and
  see
  [Namespace handling](https://github.com/dhyansraj/mcp-mesh/blob/main/helm/mcp-mesh-core/README.md#namespace-handling)
  for the `--take-ownership` path if you want the release to own its namespace
  deliberately.
- **`helm.sh/resource-policy` is reserved in `commonAnnotations`.** When the
  chart does render a `Namespace`, its `keep` is the only thing standing
  between `helm uninstall` and everything in that namespace, and a
  `commonAnnotations` value would override it on last-wins. So the chart fails
  the render when the key is set to anything but `keep` — remove it from
  `commonAnnotations`, or set it to `keep`, before upgrading. This check runs
  whether or not `namespaceCreate` is on.
- **What the namespace deletion actually looks like, if you skip the ordering
  above.** The upgrade reports `STATUS: deployed` and exit 0 while deleting the
  namespace and everything in it. When `global.namespace` matches the namespace
  passed to `-n`, it is also unrecoverable: Helm keeps the release secret in
  the `-n` namespace, which is the one being deleted. A retry while the
  namespace drains fails with `... is forbidden: ... because it is being
  terminated`, and once it is gone `helm history` reports `release: not found`.
  Helm reads `helm.sh/resource-policy` off the **live** object, which is why
  the annotation has to have landed on a previous upgrade — the chart cannot
  check for it at render time, because `lookup` returns nothing under
  `helm template`, the way Argo CD and every other GitOps renderer evaluates
  it.
