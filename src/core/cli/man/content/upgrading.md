# Upgrading a Live Mesh

> Order of operations, version-skew guarantees, schema migrations, and in-flight job safety for upgrading a running mesh

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
