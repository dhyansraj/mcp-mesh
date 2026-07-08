# Service Views

> Typed aggregation of dot-namespaced capabilities — a consumer-owned lens over capabilities, not a new registry entity

A **service view** is a consumer-owned typed aggregation of ordinary capability dependencies: a group of dot-namespaced capabilities (`media.caption`, `media.thumbnail`, `media.transcribe`, …) surfaced as one typed facade whose methods each bind a single capability. Instead of declaring five loose `McpMeshTool` dependencies and hand-wiring each proxy, you declare one typed handle and call `media.caption(...)`, `media.thumbnail(...)` as methods.

The capability stays the atom. A view is a **lens over capabilities**, not a new thing the registry stores. This is the design line that keeps the feature additive: a mesh with no views is byte-identical to a mesh before views existed.

## Why this exists

Real agents rarely depend on one capability. A media pipeline wants captioning, thumbnailing, and transcription; an HR tool wants employee lookup, org-chart, and payroll. Declared as loose dependencies, these grow into a wall of `McpMeshTool` parameters with no type telling you which is which, and the relationship between them lives only in the developer's head.

A service view names that group. The methods sort under a shared prefix, the type documents intent, and the whole aggregation is passed as one parameter. It reads like a client for a service — while remaining, on the wire, exactly the loose capability edges it replaces. That framing is a convenience, not a mandate to inject the view everywhere: because a view expands to **one dependency edge per method on the consumer** — whether you call one method or all of them — a view pays off when a consumer uses most of the group, and per-capability injection is the better fit when a handler touches only a slice. [When to use a view vs. per-capability injection](#when-to-use-a-view-vs-per-capability-injection) makes that trade-off concrete.

## The model

A view is declared once, on the consumer, and binds its methods to capabilities method by method:

=== "Python"

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

=== "TypeScript"

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

=== "Java"

    ```java
    @MeshService                     // or @MeshService(minAvailable = 2)
    public interface MediaService {
        @Selector(capability = "media.caption", required = true, tags = "+fast")
        Map<String, Object> caption(Map<String, Object> args);
        @Selector(capability = "media.thumbnail")
        Map<String, Object> thumbnail(Map<String, Object> args);
        @Selector(capability = "media.transcribe")
        Map<String, Object> transcribe(Map<String, Object> args);
    }
    ```

Each method is one selector over one capability. The facade the framework injects gives every method its **own** resolved proxy.

## The differentiator: per-method resolution

The property that separates a service view from a Feign, gRPC, or OpenAPI client is that **methods of one view may resolve to different provider agents, and each rebinds independently**.

A single-target client points at one service — one host, one deployment, one lifecycle. A service view points at a *group of capabilities*, and each capability is resolved separately by the mesh's normal dependency resolution:

```
MediaService (one consumer-side view)
   ├── caption    ──> agent-A (media-fast, v2)
   ├── thumbnail  ──> agent-B (media-core, v1)
   └── transcribe ──> agent-C (whisper-svc, v3)
```

When `agent-B` is redeployed or a better provider for `media.thumbnail` appears, only the `thumbnail` method rebinds — `caption` and `transcribe` keep their proxies untouched. There is no shared connection, no group version, no interface-level availability summary. A view is **consumer-local**: two consumers may aggregate the same capabilities differently, and neither is a contract the other has to honor.

This is DDDI applied method by method. Each method inherits hot-swap, health-aware routing, and graceful degradation independently.

## Zero wire and registry changes

A view is pure declaration sugar. At registration time each method expands into an ordinary `DependencySpec` edge — the same shape a loose dependency produces — appended to the consuming tool through the existing **required-wins dedupe**. A view over N capabilities shows as **N ordinary dependencies** in `meshctl list`, not one aggregate edge and not a new "view" record.

```
@mesh.service class of N methods
        │  expands at registration
        ▼
N ordinary DependencySpec edges  ──►  existing required-wins dedupe
        │
        ▼
each method delegates to its own per-capability resolved proxy
```

Because the expansion is byte-identical to hand-written edges, the registry, the wire protocol, and the resolution algorithm are all unchanged. If the same capability is declared both loosely and through a view, the required-wins dedupe collapses them to a single edge — the view never double-registers.

A legacy union capability (e.g. `session_state`) and its dotted successors (`session_state.record_question_score`, `session_state.*`) are independent capabilities as far as the registry is concerned — one agent can publish and another can consume both at once. That makes an incremental migration painless: stand up the dotted tools alongside the union capability, move consumers over method by method, and retire the union capability once nothing binds it.

## Binds on all four constructs

A view method is a full dependency declaration, so it binds on the same four constructs the resolver applies to any edge — method by method:

| Construct | Per-method knob |
| --------- | --------------- |
| **Capability** | the dotted name the method binds (`media.caption`) |
| **Tag** | `+preferred` / `-excluded` scoring, per method |
| **Version** | version constraint, per method |
| **Schema** | `expected_type` / `expectedType` shape matching, per method |

One method can pin `+fast` and `>=2.0.0`; the next can require a specific output schema; a third can take whatever provider is healthy. See [Tag Matching](tag-matching.md) and [Schema Matching](schema-matching.md) for how those two disambiguators work.

## Two roles

A service view shows up in two places. This page stays at the mechanism level — the exact signatures live in the SDK guides.

### 1. Consumer facade

The declaration above. In Python a class of `@mesh.selector` async stubs decorated with `@mesh.service`; in TypeScript a `mesh.serviceView({ methods })` value; in Java a `@MeshService` interface of method-level `@Selector`s. You then either autowire the facade (Java bean) or pass the view as a tool parameter (all three runtimes).

- [Dependency Injection (Python)](../python/dependency-injection.md#service-views-rfc-1280)
- [Dependency Injection (Java)](../java/dependency-injection.md#service-views-with-meshservice)
- [Dependency Injection (TypeScript)](../typescript/dependency-injection.md#service-views-rfc-1280)

The capabilities a view binds are ordinary dotted tools, each declared explicitly on its provider — `@mesh.tool(capability="media.caption")` (Python), `agent.addTool({ capability: "media.caption", ... })` (TypeScript), or `@MeshTool(capability = "media.caption")` (Java). The capability-name grammar is dot-namespacing-aware: a name is one or more dot-separated `^[a-zA-Z][a-zA-Z0-9_-]*$` segments, validated identically in the registry and every SDK.

### 2. Discovery

Because dotted capabilities carry their grouping in the name, `meshctl list --services` renders them as grouped services — **the group is the segments before the last dot** (`media.caption` and `media.thumbnail` group under `media`). This is display-only, derived entirely from the name; there is no service record behind it.

```bash
meshctl list --services            # SERVICE / METHOD / AGENT / STATUS table
meshctl list --services --verbose  # per-method provider bindings under each group
```

## Refusal semantics

This is the subtle part, and the two consumption paths behave differently on purpose.

### Bean-path facade → class-level required, no tool-scoped refusal

An autowired facade (the Java `@Autowired` bean, or any view held as a long-lived object) is a **class-level** aggregation. A `required=true` method on it behaves exactly like a class-level required dependency:

- it participates in the owning agent's **registry-carrier availability** predicate,
- it obeys **required-wins** dedupe, and
- it is promoted at the **route perimeter** (an HTTP route with the required edge unresolved returns `503 dependency_unavailable`).

But it does **not** add a tool-boundary pre-invoke refusal — because the framework cannot know *which tools* call a class-level aggregation. There is no single tool to guard, so there is no per-tool `dependency_unavailable` refusal before a handler runs.

### Tool-parameter → tool-scoped structured refusal

To get the tool-scoped structured refusal, declare the view as a **tool parameter** instead. Passed as a parameter (detected by type, following the `MeshJob` precedent), the view's methods expand into edges on **that specific tool**, so the framework knows exactly which handler to guard:

=== "Python"

    ```python
    @app.tool()
    @mesh.tool(capability="process_media")
    async def process_media(req: dict, media: MediaService = None):
        caption = await media.caption({"text": req["text"]})
        ...
    ```

=== "Java"

    ```java
    @MeshTool(capability = "process_media")
    public Map<String, Object> processMedia(Map<String, Object> req, MediaService media) {
        Map<String, Object> caption = media.caption(Map.of("text", req.get("text")));
        ...
    }
    ```

Now a `required=true` view method joins that tool's **pre-invoke guard**: if the edge is unresolved the tool returns the structured `{"error":"dependency_unavailable","capability":...}` refusal *before* the handler runs, on both the direct and claim paths, lease released — byte-identical across all three runtimes. An unresolved **optional** method degrades softly on its own call (a caught `dependency_unavailable` error in Python/TypeScript, `null`-shaped behavior in Java) rather than refusing the whole tool.

### Availability floor

Independently of per-method `required`, a view accepts an optional availability **floor** — `min_available=N` (Python), `minAvailable = N` (Java/TypeScript). When fewer than `N` of the view's methods currently resolve, **every** facade call fails fast (`MeshServiceUnavailableError` / `MeshServiceUnavailableException`), rather than letting individual calls discover the shortfall one at a time. The floor is **settle-grace-aware** — it will not burst failures while an ordinary restart lets the topology settle — and the default `0` means no floor.

## When to use a view vs. per-capability injection

A service view is a grouping convenience, not a default. The [Zero wire and registry changes](#zero-wire-and-registry-changes) section already stated the governing fact: injecting a view expands to **one dependency edge per method on the consuming handler**, regardless of how many methods that handler actually calls. Inject a 13-method view and call one method, and the handler still registers 13 edges. That single fact decides when a view earns its keep.

### When a view is the right tool

- **A consumer exercises most of the group cohesively** — an orchestrator handler that calls many of the group's actions in one flow. The edges you register are edges you use.
- **You want typed grouping plus independent per-method rebinding as a unit** — one typed handle, one prefix, and each method still hot-swaps on its own provider's health.
- **A bean-path aggregation shared across a class** — a single facade (the Java `@Autowired` bean, or a `serviceView` value reused by several handlers) that, together, covers most of the group.

### When per-capability injection is the better fit

- **A handler uses only 1–2 capabilities of the group** — declare exactly those with per-capability injection: a Python dependency on the specific `@mesh.tool` handler, a Java `@Selector` + `@MeshInject` → `McpMeshTool`, or a TypeScript dependency → `McpMeshTool`. Don't inject a 13-method view to reach two methods.
- **The consumer is a route handler** (`@mesh.route` / `mesh.route(...)` / `@MeshRoute`) — views are a tool-parameter surface and are **rejected** on routes anyway; a route declares the specific dotted capability it needs and injects that proxy.
- **Precise `required`-gating matters** — a view's `required` methods gate the handler as a set; if those methods span multiple providers, the handler is gated on capabilities it never calls. Per-capability injection gates on exactly what the handler invokes.
- **Dep-count legibility / registry footprint matters** — when you want `meshctl list` to show what a handler actually depends on, not the whole group behind one type.

### The anti-pattern, concretely

A fat view over ~13 capabilities injected into thin handlers that each call only 1–2 of its methods fans out to ~13 dependency edges **per handler**. A consumer with ~9 such handlers then shows ~120 dependency edges where ~20 would do — one observed shape had a single consumer carrying roughly 123 edges against a real need closer to 20.

Nothing is broken. Every edge resolves fine, and an unused method costs **zero call overhead** — the extra edges are only heartbeat dependency-resolution metadata, not per-request work. But the consumer is inflated and heavier to reason about, carries more registry bookkeeping, and **over-gates** when the view's `required` methods span multiple providers: the handler's pre-invoke guard can trip because a capability it never calls is down (see [Refusal semantics](#refusal-semantics)).

The fix is not to abandon views — it is to **size the view to the consumer**: keep the view where a handler uses the group, and inject the 1–2 capabilities directly where a handler uses only a slice.

### Principle and composition

A service view is a **grouping convenience, not a replacement for per-capability injection**, and it is **not a producer construct** — views never publish capabilities; the dotted tools they bind are ordinary producers declared on their own agents. Pick the shape by what the consumer does: **"I use the group"** → inject the view; **"I use a slice"** → inject exactly those capabilities per-capability. The two compose freely — keep the view where it pays off and use per-capability injection in the handlers that touch only a couple of capabilities.

## Relationship to DDDI

Service views sit directly on top of the injection primitive: each method is one DDDI edge, resolved, injected, and hot-swapped exactly like a loose dependency. The view adds typed grouping and a discovery vocabulary on top — it does not change how resolution works. See [DDDI](dddi.md) for the underlying model.

Calling a facade method (or any dotted capability) threads calling-job identity / `MeshCallContext` exactly like an ordinary tool call — a view is a lens, not a proxy hop, so the downstream fence sees the same caller it would for a loose dependency edge.

## See Also

- [DDDI](dddi.md) — the injection primitive every view method rides on
- [Tag Matching](tag-matching.md) — per-method preference scoring
- [Schema Matching](schema-matching.md) — per-method output-shape disambiguation
- [Dependency Injection (Python)](../python/dependency-injection.md#service-views-rfc-1280) — `@mesh.service` syntax
- [Annotations (Java)](../java/annotations.md#meshservice) — `@MeshService` reference
- [Dependency Injection (TypeScript)](../typescript/dependency-injection.md#service-views-rfc-1280) — `mesh.serviceView()`
