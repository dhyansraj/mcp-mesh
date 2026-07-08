# Service Views

> Typed aggregation of dot-namespaced capability dependencies — and when a view earns its keep vs. per-capability injection

## What a service view is

A **service view** is a consumer-owned typed handle over a group of dot-namespaced capability dependencies (`media.caption`, `media.thumbnail`, `media.transcribe`, …). Instead of declaring each capability as a separate `mesh.McpMeshTool` dependency and hand-wiring the proxies, you declare one view whose methods each bind a single capability, and call `media.caption(...)`, `media.thumbnail(...)` as methods.

In Python a service view is a class of `@mesh.selector` async stubs decorated with `@mesh.service`. Each method resolves **independently** through ordinary DDDI — different methods may bind different provider agents and rebind separately as the topology changes. The capability stays the atom; a view is a lens over capabilities, not a new registry entity. See `meshctl man dependency-injection` and the DDDI concept doc for the underlying model.

```python
@mesh.service                       # or @mesh.service(min_available=2)
class MediaService:
    @mesh.selector("media.caption", required=True, tags=["+fast"])
    async def caption(self, args: dict) -> dict: ...
    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...
    @mesh.selector("media.transcribe")
    async def transcribe(self, args: dict) -> dict: ...
```

## The mechanic that governs cost

Injecting a view is **not** free grouping. At registration each view method expands into one ordinary dependency edge on the consuming handler — a view over N methods becomes **N dependency edges on that consumer**, regardless of how many methods the handler actually calls. Call 1 of 13 methods and you still register 13 edges.

```
@mesh.service class of N methods, injected into one @mesh.tool handler
        │  expands at registration
        ▼
N ordinary dependency edges on THAT handler   (whether you call 1 or all N)
```

Those edges are real bookkeeping: they appear in `meshctl list`, they participate in resolution and heartbeat dependency-resolution metadata, and — for any method marked `required=True` — they gate the handler. This is the fact that decides when a view is the right tool and when it is not.

## When to use a view

Reach for a service view when the grouping earns the edges:

- **A handler exercises most of the group cohesively** — an orchestrator `@mesh.tool` that calls many of the group's actions in one flow. The edges you register are edges you use.
- **You want typed grouping plus independent per-method rebinding as a unit** — one handle, one prefix, and each method still hot-swaps on its own provider's health.
- **A bean-path aggregation shared across a class** — a single view held on the consumer and reused by several handlers that, together, cover most of the group.

## When to use per-capability injection instead

Prefer declaring the exact capabilities as ordinary dependencies when:

- **A handler uses only 1–2 capabilities of the group** — declare exactly those as per-capability dependencies on a `@mesh.tool` handler (an `McpMeshTool` proxy each). Don't inject a 13-method view to reach 2 methods.
- **The consumer is a `@mesh.route` handler** — views are a tool-parameter surface only and are **rejected** on routes anyway; a route declares the specific dotted capability it needs and injects that proxy (see the `@mesh.route` pattern in `meshctl man dependency-injection`).
- **Precise `required`-gating matters** — a view's `required` methods gate the handler as a set; if those methods span multiple providers, the handler is gated on capabilities it never calls. Per-capability injection gates on exactly what the handler invokes.
- **Dep-count legibility / registry footprint matters** — when you want `meshctl list` to show what a handler actually depends on, not the whole group behind one type.

## The anti-pattern, concretely

A fat view over ~13 capabilities injected into thin handlers that each call only 1–2 of its methods fans out to ~13 dependency edges **per handler**. A consumer with ~9 such handlers then shows ~120 dependency edges where ~20 would do — one observed shape had a single consumer carrying roughly 123 edges against a real need closer to 20.

Nothing is broken: every edge resolves fine, and an unused method costs **zero call overhead** — the extra edges are only heartbeat dependency-resolution metadata, not per-request work. But the consumer is inflated and heavier to reason about, carries more registry bookkeeping, and **over-gates** when the view's `required` methods span multiple providers: a handler can refuse (its pre-invoke `dependency_unavailable` guard trips) because a capability it never calls is down.

The fix is not to abandon views — it is to size the view to the consumer: keep the view where a handler uses the group, and inject the 1–2 capabilities directly where a handler uses only a slice.

## Principle and composition

A service view is a **grouping convenience, not a replacement for per-capability injection**, and it is **not a producer construct** — views never publish capabilities; the dotted tools they bind are ordinary `@mesh.tool(capability="media.caption")` producers declared on their own agents.

Pick the shape by what the consumer does:

- **"I use the group"** → inject the view.
- **"I use a slice"** → inject exactly those capabilities per-capability.

The two compose freely: keep a view where it pays off and use per-capability injection in the handlers that touch only a couple of capabilities. Sizing each consumer to what it actually calls keeps dep counts legible and gating precise without giving up typed grouping where it helps.

## See Also

- `meshctl man dependency-injection` — the DDDI primitive every view method rides on; `@mesh.service` / `@mesh.selector` syntax and the `@mesh.route` per-capability pattern
- `meshctl man overview` — architecture and the DDDI model
- `meshctl man jobs` — calling-job identity threads through a facade method exactly like an ordinary tool call
- `meshctl man capabilities` — dot-namespaced capability naming and `meshctl list --services` grouping
- [`docs/concepts/dddi.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/dddi.md) — the injection primitive every view method rides on
- [`docs/concepts/service-views.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/service-views.md) — narrative concept doc
