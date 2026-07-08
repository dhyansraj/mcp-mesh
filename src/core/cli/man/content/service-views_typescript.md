# Service Views

> Typed aggregation of dot-namespaced capability dependencies — and when a view earns its keep vs. per-capability injection

## What a service view is

A **service view** is a consumer-owned typed handle over a group of dot-namespaced capability dependencies (`media.caption`, `media.thumbnail`, `media.transcribe`, …). In TypeScript `mesh.serviceView({ methods })` returns a branded value you place as **one** entry in a tool's `dependencies` array; the framework injects a single facade argument whose methods each bind a single capability, instead of you declaring each capability as a separate `McpMeshTool` dependency and wiring the proxies by hand.

Each method resolves **independently** through ordinary DDDI — different methods may bind different provider agents and rebind separately as the topology changes. The capability stays the atom; a view is a lens over capabilities, not a new registry entity. See `meshctl man dependency-injection --typescript` and the DDDI concept doc for the underlying model.

```typescript
const Media = mesh.serviceView({
  methods: {
    caption: { capability: "media.caption", required: true, tags: ["+fast"] },
    thumbnail: { capability: "media.thumbnail" },
    transcribe: { capability: "media.transcribe" },
  },
  // minAvailable: 2,
});
```

## The mechanic that governs cost

Injecting a view is **not** free grouping. At registration each view method expands into one ordinary dependency edge on the consuming handler — a view over N methods becomes **N dependency edges on that consumer**, regardless of how many methods the handler actually calls. Call 1 of 13 methods and you still register 13 edges.

```
mesh.serviceView of N methods, placed in one addTool dependencies array
        │  expands in place at registration
        ▼
N ordinary dependency edges on THAT handler   (whether you call 1 or all N)
```

Those edges are real bookkeeping: they appear in `meshctl list`, they participate in resolution and heartbeat dependency-resolution metadata, and — for any method marked `required` — they gate the handler. This is the fact that decides when a view is the right tool and when it is not.

## When to use a view

Reach for a service view when the grouping earns the edges:

- **A handler exercises most of the group cohesively** — an orchestrator tool that calls many of the group's actions in one flow. The edges you register are edges you use.
- **You want typed grouping plus independent per-method rebinding as a unit** — one handle, one prefix, and each method still hot-swaps on its own provider's health.
- **An aggregation shared across several tools** — a `serviceView` value reused by handlers that, together, cover most of the group.

## When to use per-capability injection instead

Prefer declaring the exact capabilities as ordinary dependencies when:

- **A handler uses only 1–2 capabilities of the group** — declare exactly those as string/object entries in the tool's `dependencies` array, injected positionally as `McpMeshTool` proxies. Don't inject a 13-method view to reach 2 methods.
- **The consumer is a `mesh.route(...)` (or `mesh.a2a.mount(...)`) handler** — a `mesh.serviceView(...)` in those dependencies is **rejected**; declare the specific dotted capability and inject that proxy instead (see the route pattern in `meshctl man dependency-injection --typescript`).
- **Precise `required`-gating matters** — a view's `required` methods gate the handler as a set; if those methods span multiple providers, the handler is gated on capabilities it never calls. Per-capability injection gates on exactly what the handler invokes.
- **Dep-count legibility / registry footprint matters** — when you want `meshctl list` to show what a handler actually depends on, not the whole group behind one type.

## The anti-pattern, concretely

A fat view over ~13 capabilities injected into thin handlers that each call only 1–2 of its methods fans out to ~13 dependency edges **per handler**. A consumer with ~9 such handlers then shows ~120 dependency edges where ~20 would do — one observed shape had a single consumer carrying roughly 123 edges against a real need closer to 20.

Nothing is broken: every edge resolves fine, and an unused method costs **zero call overhead** — the extra edges are only heartbeat dependency-resolution metadata, not per-request work. But the consumer is inflated and heavier to reason about, carries more registry bookkeeping, and **over-gates** when the view's `required` methods span multiple providers: a handler can refuse (its pre-invoke `dependency_unavailable` guard trips) because a capability it never calls is down.

The fix is not to abandon views — it is to size the view to the consumer: keep the view where a handler uses the group, and declare the 1–2 capabilities directly where a handler uses only a slice.

## Principle and composition

A service view is a **grouping convenience, not a replacement for per-capability injection**, and it is **not a producer construct** — views never publish capabilities; the dotted tools they bind are ordinary `agent.addTool({ capability: "media.caption", ... })` producers declared on their own agents.

Pick the shape by what the consumer does:

- **"I use the group"** → inject the `serviceView`.
- **"I use a slice"** → declare exactly those capabilities per-capability in `dependencies`.

The two compose freely: keep a view where it pays off and use per-capability injection in the handlers that touch only a couple of capabilities. Sizing each consumer to what it actually calls keeps dep counts legible and gating precise without giving up typed grouping where it helps.

## See Also

- `meshctl man dependency-injection --typescript` — the DDDI primitive every view method rides on; `mesh.serviceView()` syntax and the `mesh.route()` per-capability pattern
- `meshctl man overview` — architecture and the DDDI model
- `meshctl man jobs --typescript` — calling-job identity threads through a facade method exactly like an ordinary tool call
- `meshctl man capabilities --typescript` — dot-namespaced capability naming and `meshctl list --services` grouping
- [`docs/concepts/dddi.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/dddi.md) — the injection primitive every view method rides on
- [`docs/concepts/service-views.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/service-views.md) — narrative concept doc
