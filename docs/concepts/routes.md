# Routes & Gateways

> Plain HTTP endpoints on a mesh agent — the bridge between external callers and the MCP capability mesh

A **route** is an ordinary HTTP endpoint (`GET /score`, `POST /orders`, …) hosted by a mesh agent, declared with `@mesh.route` (Python), `@MeshRoute` (Java), or `mesh.route()` (TypeScript). Its distinguishing feature is that the handler **consumes mesh capabilities**: it injects a resolved proxy for a capability it needs and calls it directly. A route is therefore a gateway — an external HTTP surface on the front, the MCP capability mesh on the back.

This is the seam where the mesh meets the rest of the world. Callers that speak HTTP (browsers, webhooks, mobile apps, another team's service) don't speak MCP and don't participate in dependency resolution. A route lets a mesh agent expose a stable HTTP API to them while orchestrating live mesh capabilities behind it — a request comes in over HTTP, the handler calls one or more resolved capabilities, and a normal HTTP response goes back out.

## Why this exists

MCP capabilities are consumed by *other agents* through dependency injection — the caller declares a dependency, the mesh resolves it, and the caller invokes a proxy. That model is perfect between agents and useless to an external HTTP client, which has no proxy, no heartbeat, and no place in resolution.

Routes close that gap without inventing a second mesh. Instead of standing up a separate API service that then has to reach into the mesh over some ad-hoc channel, you host the HTTP endpoint *on a mesh agent* and let it inject the capabilities it needs the same way any consumer would. The gateway and the mesh consumer are the same process, so the route inherits health-aware routing, hot-swap, and the required-dependency perimeter for free — it is a first-class mesh consumer that happens to be triggered by HTTP rather than by another agent's call.

## How a route consumes capabilities

A route handler injects a **specific capability** and calls its proxy. This is per-capability injection — the handler names the exact capability it depends on and receives a resolved proxy for it, rather than receiving an aggregate:

```
external HTTP request
        │
        ▼
route handler  ──── injects proxy for capability "session_state.record_question_score"
        │
        ▼
resolved provider agent ──► result ──► HTTP response
```

The per-runtime surface differs — Java pairs `@MeshRoute(dependencies = {…})` with a `@MeshInject` parameter typed `McpMeshTool<…>`; Python and TypeScript declare the dependency on the route and receive the proxy — but the shape is the same everywhere: one route, the specific capabilities it names, one resolved proxy per capability, called inline in the handler. The exact declaration syntax lives in the dependency-injection guides linked below.

Because the proxy is an ordinary resolved dependency, everything DDDI gives a consumer applies here too: the capability hot-swaps to a better or healthier provider between requests, calls thread call context and appear in the audit trail, and an unavailable optional capability injects a null/unavailable proxy that the handler can fall back around.

## The route perimeter

Routes get a guarantee tools reach through a different mechanism: a **pre-invoke 503**. When a route declares a capability as **`required`** and that capability is unresolved at request time, the framework returns `503` with body `{"error":"dependency_unavailable","capability":"…"}` **before the handler runs** — after the settle window has passed, so an ordinary restart or topology settle doesn't burst spurious 503s.

This matters because an external caller can't inspect a proxy for `null` the way an in-mesh consumer can. The perimeter turns "a dependency this endpoint cannot work without is missing" into a clean, standard HTTP failure at the edge, instead of letting the request reach a handler that would then dereference an unavailable proxy. It is the HTTP-facing analogue of the tool-boundary refusal that tools get.

Two properties are worth committing to memory:

- **`required` defaults to false.** Left at the default, an unresolved capability injects an unavailable proxy and the request falls through to the handler's own graceful-degradation logic — no automatic 503. You opt *into* the perimeter by marking the edge `required`.
- **The 503 fires only for `required` edges, at the perimeter, after settle.** A required-dep 503 takes precedence over coarser missing-dependency flags; non-required missing deps never trip it.

(One nuance from the runtime guides: a streaming route can't carry a pre-body status code, so it bypasses the perimeter and keeps soft-fail semantics — the handler checks for the unavailable proxy itself.)

## Routes vs. tools

Routes and tools are two different ways an agent exposes behavior **over the network** — mesh serves both over HTTP (it uses the MCP **Streamable HTTP** transport and does not use stdio), so neither is "internal." What differs is the **protocol** each speaks and the **role** each plays:

| | **Route** | **Tool** |
| --- | --- | --- |
| Protocol | plain HTTP — any REST path you define | MCP (`/mcp`: `tools/list` + `tools/call`) |
| Caller | anything that speaks HTTP — a browser, `curl`, a webhook, a mobile app | any MCP client, or another mesh agent that resolved it as a dependency |
| Role | a **gateway** that consumes capabilities | a **capability** other agents discover, resolve, and hot-swap |
| In the dependency graph | no — a route only consumes | yes — a tool is a provider |
| Missing required dep | `503` at the perimeter, pre-handler | structured `dependency_unavailable` refusal, pre-invoke |

The practical line: **a tool speaks MCP and is a resolvable mesh capability; a route speaks plain HTTP for callers that don't speak MCP.** Both are reachable over the network — reach for a route when the caller is a browser, webhook, or other non-MCP HTTP client, and a tool when you want a first-class mesh capability. A mesh tool is directly callable by any MCP client over HTTP precisely because mesh serves it over Streamable HTTP rather than stdio; a route is what you add when the caller doesn't speak MCP at all. A route consumes capabilities but does not publish one (you don't resolve a route as a dependency); a tool publishes a capability and is consumed by resolution.

This is also why a **service view is rejected in a route.** A [service view](service-views.md) is a tool-parameter / bean surface: it aggregates many capabilities behind one typed facade, and its refusal semantics are designed around a *tool* boundary. A route needs a concrete perimeter for a concrete capability, so a view facade is not accepted as a route's injected dependency — the framework rejects it at boot. A route takes **per-capability injection** instead: name the specific capability the endpoint needs (including a single dotted capability a view would otherwise group) and inject that one proxy. When a handler genuinely needs a slice of a group, per-capability injection is also the better fit for exactly the gating reasons the Service Views page details.

## Relationship to DDDI

A route is a DDDI consumer with an HTTP trigger. Each capability it injects is one resolved dependency edge — same heartbeat-driven proxy lifecycle, same auto-rewiring on topology change, same availability semantics — and the required-edge perimeter is the same required-dependency propagation the mesh applies everywhere, surfaced at the HTTP boundary as a status code instead of a proxy going null. See [DDDI](dddi.md) for the resolution model and [Service Views](service-views.md) for why the aggregate facade stays on the tool/bean side of that line.

## Per-SDK guides

This page stays at the concept level; the exact route declaration, dependency wiring, and injection syntax live in the runtime guides:

- [Dependency Injection (Python)](../python/dependency-injection.md#required-dependencies) — `@mesh.route`, required deps, the 503 perimeter
- [Dependency Injection (Java)](../java/dependency-injection.md#views-and-meshroute) — `@MeshRoute` + `@MeshInject`, per-capability injection
- [Dependency Injection (TypeScript)](../typescript/dependency-injection.md#required-dependencies) — `mesh.route()`, required deps, the 503 perimeter

## See Also

- [DDDI](dddi.md) — the resolution primitive every route dependency rides on
- [Service Views](service-views.md) — the tool/bean-side aggregation that a route rejects
- [LLM Agents](llm.md) — the other agent surface that consumes many capabilities
- [Health & Discovery](health-discovery.md) — how the availability a route perimeter reads is computed
