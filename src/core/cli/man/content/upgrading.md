# Upgrading a Live Mesh

> Order of operations, version-skew guarantees, schema migrations, in-flight job safety, and source migrations for upgrading a running mesh

## 3.4.0 — Dependency injection is positional everywhere

**Breaking, Java and TypeScript. Python is unchanged.** As of 3.4.0 the Nth declared dependency binds to the Nth injectable parameter, at every injection site in every runtime. Parameter names, capability keys and `@MeshInject` values are never used to *select* a dependency.

Two sites changed:

| Runtime    | Site                              | Before                          | After                     |
| ---------- | --------------------------------- | ------------------------------- | ------------------------- |
| Java       | `@MeshRoute`, `@MeshA2A`          | by `@MeshInject` value / by parameter name | by position    |
| TypeScript | `mesh.route`, `mesh.a2a.mount`    | object keyed by capability      | positional array          |

Java `@MeshTool`, TypeScript `addTool`, and every Python site were already positional, so their *binding* is untouched. One caveat at `@MeshTool`: `@MeshInject` is now honoured on its parameters, where it was previously ignored, so a value that disagrees with its parameter's position now fails at boot.

### Find your exposure before you upgrade

A handler declaring **two or more** dependencies can rebind when its declaration order disagrees with its old names. Do not use the dependency count as a filter, though — one dependency is exempt only in narrow cases, and they differ by runtime. In TypeScript there is no exemption at all: the *callback shape* changed, so a sole-dependency handler still written `async (req, res, { cap }) => ...` throws through the new guard exactly as a five-dependency one does. In Java a single dependency is exempt only when its `@MeshInject` already names the declared capability, or carries none — a sole `@MeshInject` naming something else selected nothing on 3.3 and was injected `null`, and on 3.4 it is a false assertion that fails the boot.

The 3.3.x Java SDK already ships the detector that finds them, and it warns without changing behaviour. Upgrade to the latest 3.3.x first, start each Spring Boot app, and grep the startup log:

```bash
grep -n "declaration order\|parameter names disagree\|BY POSITION (issue #1401)" app.log
```

```text
@MeshRoute com.example.api.ApiController.report(McpMeshTool, McpMeshTool): parameter
names disagree with declaration order, so these parameters do NOT bind the way their
names suggest.
  2 declared dependencies: [0] 'get_employee', [1] 'employee_count'
    slot 0 = parameter 0 (McpMeshTool employee_count)
        parameter name 'employee_count' used to bind:   dependency[1] 'employee_count'
        binds (by position):                            dependency[0] 'get_employee'
  If this handler was written for mcp-mesh 3.3 or earlier (when @MeshRoute and @MeshA2A
  bound by name), fix it — pick one:
    • reorder dependencies = {...} to: [0] 'employee_count', [1] 'get_employee'
```

The two **reorder** fixes it prescribes are behaviour-preserving on 3.3 *and* correct on 3.4 — moving whole `@MeshDependency` entries, or moving the parameters, is name-neutral under the old rule — so you can land those before upgrading. Its third suggestion, *adding* an `@MeshInject` where the parameter carried none, preserves 3.3 behaviour only where the parameter name already selected that same dependency; where the name matched no declared capability, 3.3 injected `null` and the annotation starts injecting a real proxy. `MCP_MESH_STRICT_DI=true` turns the warnings into a startup failure if you want the sweep enforced in CI.

TypeScript has no equivalent pre-upgrade signal, but it cannot misbind either: string keys and array indices are disjoint, so a stale `deps.capability` throws rather than silently returning another dependency's proxy.

### Java — `@MeshInject` becomes an assertion

`@MeshInject` no longer selects a dependency; it asserts the one position already assigns, and a contradiction fails the boot **unconditionally** (not gated on `MCP_MESH_STRICT_DI`). Reorder the declaration list to match the parameters, or drop the annotations — on 3.4 binding is identical either way. Drop them only *after* upgrading, though: on 3.3 `@MeshInject` still selects the dependency, so removing it there falls back to parameter-name matching and can rebind a running application.

```java
// Before (3.3) — bound by @MeshInject value; declaration order was irrelevant.
@MeshRoute(dependencies = {
    @MeshDependency(capability = "get_employee"),
    @MeshDependency(capability = "employee_count")
})
public ResponseEntity<Report> report(
        @MeshInject("employee_count") McpMeshTool<Integer> stats,
        @MeshInject("get_employee") McpMeshTool<Employee> lookup) { ... }

// After (3.4) — declaration order IS the binding. Reorder one end.
@MeshRoute(dependencies = {
    @MeshDependency(capability = "employee_count"),
    @MeshDependency(capability = "get_employee")
})
public ResponseEntity<Report> report(
        @MeshInject("employee_count") McpMeshTool<Integer> stats,
        @MeshInject("get_employee") McpMeshTool<Employee> lookup) { ... }
```

An unannotated handler is the same fix with the annotations absent — the parameter names carry no meaning, so either reorder `dependencies = {...}` or reorder the parameters.

### TypeScript — destructure the array

```typescript
// Before (3.3)
mesh.route(["add", "greet_lucky"], async (req, res, { add, greet_lucky }) => { ... });

// After (3.4)
mesh.route(["add", "greet_lucky"], async (req, res, [add, greetLucky]) => { ... });
```

```typescript
// Before (3.3)
mesh.a2a.mount(app, config, async (deps, payload) => {
  const dateService = deps["date_service"] as McpMeshTool | null;
});

// After (3.4)
mesh.a2a.mount(app, config, async ([dateService], payload) => { ... });
```

Reading a **declared** capability by name on the new array throws with the index and the rewrite:

```text
mesh.route dependencies are positional as of 3.4.0.
You accessed `deps.add`; "add" is declared dependency [0].
Rewrite the handler as:  async (req, res, [add, greet_lucky]) => { ... }
```

`RouteDependencies` and `A2ADependencies` now alias `PositionalDependencies` (`Array<McpMeshTool | null>`), so an object type argument such as `mount<{ date_service: McpMeshTool }>(...)` stops compiling. Use a per-slot tuple: `mount<[McpMeshTool | null]>(...)`.

### What does not change

Correctly-ordered code is unaffected — the whole in-tree corpus was measured on both sides of the conversion: **Java 21 handlers, 0 binding differences; TypeScript 35 handlers, 0 binding differences.** Slot preservation is unchanged too: an unresolved dependency holds its own index as `null` and never shifts a later one up.

Full guide with every before/after: <https://mcp-mesh.ai/migration/3.4-positional-di/>

## Recommended Order

Upgrade the **registry first, then the agents**.

The registry runs its schema migration at startup (see *Schema Migrations*), so bringing it up first means the new columns exist before any newer-SDK agent tries to use them. The compatibility contract (see *Version Skew*) holds in both directions, so agents can trail the registry by a version with no hard failure — but registry-first is the order with the fewest moving parts: migrate once, then roll agents at your own pace.

## Version Skew

A mixed-version mesh always converges to the **older side's semantics** — there is no hard failure when registry and SDK versions differ. This is the compatibility contract:

- **Newer registry, older-SDK agents.** Older agents post epoch-less job deltas. The registry validates these **owner-only, with no fencing** — the legacy path. Event reads without identity parameters are served **anonymously** (unchanged). When an agent sends no identity headers, the registry's identity accessors read null and it falls back to legacy handling.
- **Older registry, newer-SDK agents.** The newer SDK's epoch and identity headers are simply unknown fields to an older registry and are ignored — so the same legacy, owner-only behavior results.

In both directions the behavior degrades to the pre-fencing legacy path by design. The only thing you lose in a skewed mesh is claim-epoch fencing (dual-ownership protection) — which is exactly why an upgrade should drain in-flight jobs rather than rely on fencing across the restart (see *In-Flight Job Safety*).

## Schema Migrations

The registry runs **ent automigrate at startup** — it reconciles the database schema against the compiled models on every boot. New releases add columns; automigrate applies them automatically. **There is no manual migration step.**

Forward upgrade (new registry against an existing database) is purely **additive** — new columns are created, existing data is untouched.

**Rollback caveat.** Automigrate runs with drop-column and drop-index enabled. If you downgrade the registry binary, its older schema no longer declares the newer columns, so the startup migration will **drop them**. The older binary operates correctly afterward (it never referenced those columns), but the drop is **destructive** — any state held in the newer columns (e.g. claim-epoch/lease bookkeeping for in-flight jobs) is lost and does not come back if you later re-upgrade. Treat a registry downgrade as forward-only-safe: fine for the running version, not a non-destructive rollback.

## In-Flight Job Safety

Job rows persist across a registry restart, but **leases cannot renew while the registry is down**. During downtime:

- job completions retry against the unreachable registry,
- event-gated (`input_required`) jobs **freeze** rather than drain — their gates stall because consumer answers cannot be posted,
- lease clocks keep advancing, so a lease can expire across the outage window.

On restart the orphan/expired-lease **reclaim sweep** races the owner's first renewing poll: whichever lands first wins. If the sweep reclaims first, a newer-SDK owner's next delta carries a stale epoch and is fenced (`claim_superseded`) — safe. But an **older, unfenced SDK** that is re-claimed by the same instance can produce **dual ownership** (double execution), because epoch-less deltas get owner-only validation with no fencing.

**Therefore: drain before a live upgrade** rather than pulling the registry out from under in-flight jobs.

```bash
# 1. Pause new claims; block until every in-flight job releases its owner
meshctl registry drain --wait

# 2. Upgrade / restart the registry (in-flight jobs have finished; queue is safe)

# 3. Resume normal dispatch — queued jobs become claimable again (FIFO)
meshctl registry resume
```

While draining, new claims are paused (queued jobs stay queued — no attempt is burned), `working` jobs keep renewing their leases and complete normally, and submissions are still accepted for after resume. `drain --wait` returns once `live_claims` reaches zero, and aborts with an error if the registry stops draining mid-wait (a concurrent `resume` or restart) rather than falsely reporting the window is safe.

> Note: an event-gated job parked in `input_required` counts as a live claim and holds the drain open until it is answered or completes — answer or cancel such jobs before draining if you need a bounded window.
>
> Multi-replica (HA): drain state is per-replica and in-memory (not shared; a restart clears it). A load balancer may route each `meshctl registry` command to a different replica, so status can flap and one `registry drain` pauses only the replica that served it — drain EVERY replica (target each address with `--registry-url`) before an HA upgrade.
>
> Separate admin port: if the registry runs a dedicated admin port (`MCP_MESH_ADMIN_PORT`), the `/admin/drain` endpoints live only on that port — pass `--registry-url http://<host>:<admin-port>`.

See the **Drain Mode** section of `meshctl man registry` for the full command reference (`status`, `--wait-timeout`, `--poll-interval`).

## Helm Mechanics

For Kubernetes deployments, upgrade **in place** with `helm upgrade` — not by uninstalling and reinstalling.

```bash
# Preserve the existing release's env/values across the upgrade
helm upgrade <release> <chart> --reuse-values

# Verify the effective values before and after
helm get values <release>
```

- **`--reuse-values`** carries forward the environment configuration set at install time so an upgrade does not silently reset it. Confirm with `helm get values` that the values you expect are still present.
- **Do not use `helm uninstall` as an upgrade mechanism.** To change the core, `helm upgrade` the existing release — uninstalling and reinstalling discards the release's history and values along with the running workloads, for no benefit.
- **`helm uninstall` is still a legitimate, explicit teardown.** It removes the core workloads (registry, PostgreSQL, Redis, and any observability components), takes the registry offline with them, and leaves the `Namespace` in place — the core chart's `Namespace` carries `"helm.sh/resource-policy": keep`, so Helm skips it on uninstall and the deletion cannot cascade to co-located agents, Secrets, and PVCs. (Releases installed with an older chart pick the annotation up on `helm upgrade`, with no values change.) The registry's contents are derived state: agents re-register on their next heartbeat, so the registry repopulates itself and the cost is a transient topology gap, not data loss. Agents keep serving while it is down — resolved dependencies are never cleared on a registry disconnect. What pauses is topology detection: discovering new capabilities, re-resolving changed ones, and looking up an agent a client has not already resolved. What is *not* derived is application data — if your own workloads used the bundled PostgreSQL or Redis for their own storage, that data is yours to protect before you tear anything down.
- **`helm.sh/resource-policy` is reserved in `commonAnnotations`.** The chart's `keep` on the `Namespace` is what keeps that cascade from happening and a `commonAnnotations` value would override it on last-wins, so the chart fails the render when the key is set to anything but `keep` — remove it from `commonAnnotations`, or set it to `keep`, before upgrading.
- **`helm uninstall` no longer reclaims Grafana's data volume.** Grafana's PVC picks up `"helm.sh/resource-policy": keep` on upgrade — a metadata-only patch, no pod restart — because the dashboards, annotations, users, and API keys in `grafana.db` are not derived from anything the mesh can replay. A reinstall under the same release name adopts the claim, data intact; reclaim it deliberately with `kubectl delete pvc <release>-mcp-mesh-grafana-pvc -n <ns>`.
- **Tempo's PVC is deleted by this upgrade, and that is intended.** `mcp-mesh-tempo.tempo.persistence.enabled` now defaults to `false`, so the claim leaves the rendered manifest and Helm reclaims it on the next `helm upgrade` — Tempo comes back on an `emptyDir`. What is lost is the volume plus up to `retention` (default `1h`) of buffered traces: it is a rolling buffer under active retention, not durable storage (3.1MB measured after 25 hours of uptime on a live install). Nothing else on the release is affected, and ingestion resumes normally. The `ReadWriteOnce` claim it required is a real rollout constraint on a single-replica Deployment, which is what deadlocked the chart on multi-node clusters — paid for minutes of traces. To keep the volume, pin the old value in the same upgrade: `--set mcp-mesh-tempo.tempo.persistence.enabled=true`. Setting it afterward provisions a new, empty claim rather than recovering the reclaimed one. Deliberately the opposite of Grafana's treatment above.
