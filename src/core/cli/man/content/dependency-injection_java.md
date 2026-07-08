# Dependency Injection (Java/Spring Boot)

> Automatic wiring of capabilities between agents

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a tool declares a dependency via `@Selector`, the mesh automatically injects a `McpMeshTool<T>` proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Tool declares dependencies via `@MeshTool(dependencies = @Selector(...))`
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh injects `McpMeshTool<T>` instances as method parameters
5. **Invocation**: Calling the proxy routes to the remote agent

## Resolution Pipeline

When the registry resolves one of your dependencies, candidate providers flow through a fixed sequence of filter stages:

```
health → capability_match → tags → version → schema → tiebreaker
```

| Stage              | What it filters on                                                          |
| ------------------ | --------------------------------------------------------------------------- |
| `health`           | Drops unhealthy / deregistering candidates first                            |
| `capability_match` | Indexed query on the capability name                                        |
| `tags`             | Required / preferred / excluded tag filter (with scoring)                   |
| `version`          | Semver constraint (bare `4.6.0` = exact; `>=2.0.0`, `^1.4`, ...)            |
| `schema`           | Opt-in schema check (issue #547) — see below                                |
| `tiebreaker`       | Highest tag-match score, then **highest version**, then agent ID            |

Every decision the registry makes is recorded as a `dependency_resolved` (or `dependency_unresolved`) event. Use `meshctl audit <agent>` to read them back — see `meshctl man audit`.

## Declaring Dependencies

### Simple Dependency

```java
@MeshTool(capability = "smart_greeting",
          description = "Greet with current date",
          dependencies = @Selector(capability = "date_service"))
public GreetingResponse smartGreet(
        @Param(value = "name", description = "The name to greet") String name,
        McpMeshTool<String> dateService) {

    if (dateService != null && dateService.isAvailable()) {
        String today = dateService.call();
        return new GreetingResponse("Hello " + name + "! Today is " + today);
    }
    return new GreetingResponse("Hello " + name + "!");
}
```

**Important**: Dependencies are injected as `McpMeshTool<T>` parameters on the method. They may be `null` if unavailable.

### Dependencies with Filters

Use the `@Selector` annotation with tags or version to filter providers:

```java
@MeshTool(capability = "report",
          description = "Generate report with formatted data",
          dependencies = @Selector(capability = "data_service",
                                    tags = {"+fast", "-deprecated"}))
public String generateReport(
        @Param(value = "query", description = "Report query") String query,
        McpMeshTool<String> dataService) {

    if (dataService == null || !dataService.isAvailable()) {
        return "Data service unavailable";
    }
    return dataService.call("query", query);
}
```

### Schema-Aware Filtering (issue #547)

Add `expectedType` (and optionally `schemaMode`) to the `@Selector` to opt the dependency into the schema stage. Producers whose published `outputSchema` doesn't satisfy the expected type are evicted with `SchemaIncompatible`.

```java
@MeshTool(
    capability = "hr_report",
    dependencies = @Selector(
        capability   = "lookup_employee",
        expectedType = Employee.class,
        schemaMode   = SchemaMode.SUBSET   // or STRICT; defaults to SUBSET when expectedType is set
    )
)
public Report hrReport(McpMeshTool<Employee> employeeLookup) { ... }

public record Employee(@NotNull String id,
                       @NotNull String name,
                       @NotNull String department) {}
```

For Spring web routes, the equivalent annotation is `@MeshDependency` (used inside `@MeshRoute(dependencies = {...})`):

```java
@MeshRoute(dependencies = {
    @MeshDependency(
        capability   = "lookup_employee",
        expectedType = Employee.class,
        schemaMode   = SchemaMode.SUBSET
    )
})
@PostMapping("/report")
public ResponseEntity<Report> report(McpMeshTool<Employee> employeeLookup) { ... }
```

> Note: Use `@NotNull` (`jakarta.validation.constraints`) on required fields. Java reference types are nullable by default; `@NotNull` is required for cross-language `STRICT` matching with Python/TypeScript counterparts.

See `meshctl man schema-matching` for `SUBSET` vs `STRICT` semantics, the cross-language convention table, and the `MCP_MESH_SCHEMA_STRICT` env knob.

## Component-level dependency declaration with `@MeshDependsOn`

`@MeshInject` and `@MeshRoute(dependencies=...)` work at the controller-method scope. For everything else — `@Service` beans, `@Component`s, servlet `Filter`s, `@Scheduled` jobs — declare the capabilities your bean needs with the class-level `@MeshDependsOn` annotation. The auto-configuration then registers a singleton `McpMeshTool` bean named by each capability, so you can wire it the standard Spring way.

### Constructor injection (recommended)

```java
@Service
@MeshDependsOn({
    @MeshDependency(capability = "list_holidays"),
    @MeshDependency(capability = "get_user_profile")
})
public class StaffSyncService {
    private final McpMeshTool<List<Holiday>> holidays;
    private final McpMeshTool<UserProfileResponse> profile;

    public StaffSyncService(
            @Qualifier("list_holidays") McpMeshTool<List<Holiday>> holidays,
            @Qualifier("get_user_profile") McpMeshTool<UserProfileResponse> profile) {
        this.holidays = holidays;
        this.profile = profile;
    }

    public List<Holiday> upcomingHolidays() {
        if (!holidays.isAvailable()) return List.of();
        return holidays.call();
    }
}
```

### Field injection

```java
@Component
@MeshDependsOn(@MeshDependency(capability = "list_holidays"))
public class HolidayChecker {
    @Autowired
    @Qualifier("list_holidays")
    private McpMeshTool<List<Holiday>> holidays;
}
```

### Where to use it

| Scenario | Annotation |
| -------- | ---------- |
| `@MeshTool` method needing remote helpers | `@MeshTool(dependencies = @Selector(...))` + parameter injection |
| `@RestController` handler method | `@MeshRoute(dependencies = {...})` + `@MeshInject` parameter |
| `@Service` / `@Component` / `Filter` / `@Scheduled` / any other Spring bean | **`@MeshDependsOn` + `@Qualifier`** |
| Several capabilities behind one typed facade | **`@McpMeshService` interface + `@Autowired`** |

`@MeshDependsOn` and `@MeshInject`/`@MeshRoute` are complementary — same heartbeat-driven proxy lifecycle, same auto-rewiring on topology change, same `isAvailable()` semantics. Pick the surface that matches where you need the dependency. If the same capability shows up via multiple sources the framework deduplicates: a single proxy and a single registry entry per capability name.

### Tags, version, and bean-name conflicts

The `@MeshDependency` element accepts the same `tags`, `version`, `expectedType`, and `schemaMode` fields documented above for `@MeshRoute`. If a `@MeshDependsOn` capability happens to match the name of a user-owned Spring bean, the user's bean wins — the framework logs an `ERROR` naming the conflicting bean's class and every `@MeshDependsOn`-annotated class that declared the capability, then skips the proxy registration. Any consumer that `@Qualifier`-injected `McpMeshTool<...>` for that capability will fail context refresh with `BeanNotOfRequiredTypeException`. Resolve by renaming either the user bean or the capability.

### Typed deserialization

When you set `expectedType` on `@MeshDependency`, the framework wires it into the `McpMeshTool` proxy's deserialization type at registration time. The first call returns the typed value directly — no extra `setReturnType(...)` step required:

```java
@Service
@MeshDependsOn(@MeshDependency(
    capability   = "get_user_profile",
    expectedType = UserProfileResponse.class))
public class StaffSyncService {
    public StaffSyncService(@Qualifier("get_user_profile") McpMeshTool<UserProfileResponse> profile) {
        // profile.call(...) returns UserProfileResponse, not Map<String,Object>
    }
}
```

If you omit `expectedType` and the `@Qualifier`-injected field is declared as `McpMeshTool<UserProfileResponse>`, deserialization to that generic type is best-effort and the first call may return `Map<String, Object>` until something else (a `@MeshRoute` parameter with the same generic, an explicit `setReturnType(...)`) primes the proxy. Setting `expectedType` is the supported way to make typed responses work upfront from a `@MeshDependsOn` surface.

### Discovery caveat — `@Bean` factory methods returning a supertype

`@MeshDependsOn` is read off the bean's resolved class via Spring's bean-definition metadata, then `AnnotationUtils.findAnnotation` walks the class and its supertypes. This covers `@Component`-scanned beans AND `@Bean` factory methods — both surfaces work as expected when the annotation is on the class Spring sees.

| Shape | Discovered? |
| --- | --- |
| `@Component @MeshDependsOn(...) class Foo` | ✓ |
| `@Bean public ConcreteFoo foo()` where `@MeshDependsOn` is on `ConcreteFoo` | ✓ — Spring's `ResolvableType` reports the concrete return type |
| `@Bean public Foo foo()` where `@MeshDependsOn` is on `Foo` (or any supertype `Foo` extends) | ✓ |
| `@Bean public Foo foo() { return new ConcreteFoo(); }` where `@MeshDependsOn` is ONLY on `ConcreteFoo` | ✗ — `findAnnotation` walks supertypes of the declared return type, not subtypes of it |

Only the last shape is a real gap. If your factory method declares a supertype return, either narrow the declared return type to the concrete class, or place `@MeshDependsOn` on the supertype itself (or on the `@Configuration` class).

## Service Views with `@McpMeshService`

A **service view** aggregates several capability dependencies behind one typed interface. Annotate an interface with `@McpMeshService`; each abstract method binds one capability via a method-level `@Selector`. Spring auto-discovers the interface and injects a facade bean (named by the decapitalized interface name) that you `@Autowired` and call directly.

The differentiator: **each method delegates to its own per-capability resolved proxy**, so different methods can resolve to different provider agents and rebind independently as the topology changes. The group is a typed view; the capability remains the atom. Nothing group-shaped crosses the wire — every method expands into an ordinary dependency edge with `required`/`tags`/`version`/settle semantics identical to a `@MeshDependsOn` dependency. A view over N capabilities therefore shows as **N separate dependencies** in `meshctl list`, not one.

```java
@McpMeshService
public interface MediaService {
    @Selector(capability = "media.caption", required = true) CaptionResult    caption(CaptionRequest req);
    @Selector(capability = "media.thumbnail")                ThumbnailResult  thumbnail(ThumbnailRequest req);
    @Selector(capability = "media.transcribe")               TranscriptResult transcribe(TranscribeRequest req);

    record CaptionRequest(String assetId, String text) {}
    record ThumbnailRequest(String assetId, int width) {}
    record CaptionResult(String assetId, String caption, String provider) {}
    record ThumbnailResult(String assetId, String uri, String size, String provider) {}
    record TranscriptResult(String assetId, String transcript, int wordCount, String provider) {}
}
```

The consumer autowires the facade and calls its methods directly. Because each method is its own edge, the results below may come from three different provider agents through one interface:

```java
@MeshAgent(name = "media-gateway", version = "1.0.0", port = 8113)
@SpringBootApplication
public class MediaGatewayApplication {
    private final MediaService media;

    public MediaGatewayApplication(MediaService media) {
        this.media = media;
    }

    @MeshTool(capability = "process_media",
              description = "Run an asset through a media service view")
    public Map<String, Object> processMedia(
            @Param(value = "assetId", description = "Asset id") String assetId,
            @Param(value = "text", description = "Source text") String text) {

        Map<String, Object> out = new LinkedHashMap<>();

        // REQUIRED edge — expected to resolve; a failure surfaces to the caller.
        out.put("caption", media.caption(new MediaService.CaptionRequest(assetId, text)));

        // OPTIONAL edge — degrade gracefully when its provider is offline.
        try {
            out.put("thumbnail", media.thumbnail(new MediaService.ThumbnailRequest(assetId, 320)));
        } catch (MeshToolUnavailableException e) {
            out.put("thumbnail", "(no thumbnail — provider offline)");
        }
        return out;
    }
}
```

### Method rules

- Every abstract method must carry `@Selector` with a non-empty `capability`. `default` / `static` interface methods are allowed and are not expanded as edges.
- Parameters follow the `@MeshTool` convention: **0 params** → no-arg call; **exactly 1 unannotated POJO/record param** → that object becomes the params (scalars still need `@Param`); **2+ params** → each needs `@Param("name")`.
- Return `T` (synchronous), `CompletableFuture<T>` (async), or `java.util.concurrent.Flow.Publisher<String>` (streaming).

A method taking several arguments must name each one with `@Param` — the single-record shorthand only applies when there is exactly one unannotated POJO/record parameter:

```java
@McpMeshService
public interface SessionService {
    // 2+ params → each carries @Param; they become the target tool's named args
    @Selector(capability = "session_state.record_question_score", required = true)
    Map<String, Object> recordQuestionScore(
            @Param("sessionId") String sessionId,
            @Param("questionId") String questionId,
            @Param("score") int score);

    // exactly one unannotated record → the record becomes the params
    @Selector(capability = "session_state.summary")
    SessionSummary summary(SummaryRequest req);
}
```

### Views as tool parameters

A view can also be consumed as a `@MeshTool` method **parameter** instead of an autowired bean. The view's methods then become dependency edges **on that tool** — declared after the tool's explicit `@Selector` deps, name-sorted per view, and in parameter order when a method takes several views — so the tool's dep count in `meshctl list` includes them. A view parameter must **not** carry `@Param`.

```java
@MeshTool(capability = "process_media",
          dependencies = @Selector(capability = "audit_log"))
public Result processMedia(
        @Param(value = "assetId", description = "Asset id") String assetId,
        McpMeshTool<String> auditLog,
        MediaService media) {   // view param → media.caption + media.thumbnail + media.transcribe edges
    ...
}
```

The same interface can be used both ways at once — autowired as a bean **and** passed as a tool parameter. The two consumption styles resolve independently (each dependency event feeds both the tool's wrapper slot and the shared bean facade), but shared capabilities register as a **single** wire edge: the tool-declared edge wins, and the bean path's synthetic carrier only registers capabilities not already declared elsewhere — so `meshctl list` shows N edges, not 2N. `minAvailable` still applies at the facade. Crucially, a `required = true` view method now participates in **that tool's** pre-invoke guard: if the edge is unresolved the tool returns the structured `dependency_unavailable` refusal before the handler runs, on both the direct and claim paths — exactly like a tool-declared `@Selector` dependency.

### Views and `@MeshRoute`

A `@McpMeshService` view interface is a **tool-parameter / bean-only** surface: used as a `@MeshRoute` handler parameter it is **rejected** at boot (a view facade cannot become a route perimeter). A route consumes a specific capability via `@MeshInject` instead — including a single dotted capability that a view would otherwise group. Declare the capability in the route's `dependencies = {}` and inject its proxy by name:

```java
@MeshRoute(dependencies = {
    @MeshDependency(capability = "session_state.record_question_score", required = true)
})
@PostMapping("/score")
public ResponseEntity<Map<String, Object>> score(
        @RequestBody ScoreRequest body,
        @MeshInject("session_state.record_question_score") McpMeshTool<Map<String, Object>> recordScore) {
    return ResponseEntity.ok(recordScore.call(Map.of(
        "sessionId", body.sessionId(),
        "questionId", body.questionId(),
        "score", body.score())));
}
```

`@MeshDependency.required()` **defaults to `false`** — set `required = true` to get the pre-invoke `503 dependency_unavailable` perimeter guard before your handler runs (after the settle window). Left at the default, an unresolved dotted capability injects an unavailable proxy and the route falls through to your own `isAvailable()` handling.

### Required, optional, and the availability floor

`required = true` on a view method behaves like a class-level `@MeshDependsOn` required dependency (see [Required Dependencies](#required-dependencies) below): it participates in cross-source required-wins dedupe, flips the registry-side availability of that capability's carrier when unresolved (visible in `meshctl list` and the registry API), and promotes any matching route-perimeter 503 guard. An optional method whose provider is down throws `MeshToolUnavailableException` on **that call only**; catch it for graceful degradation while the rest of the view keeps working.

> **One difference when injected as a bean.** An autowired view facade is class-level, so the framework cannot know which `@MeshTool` methods call it and does **not** add a pre-invoke structured `dependency_unavailable` refusal to those tools — a call to a required-but-unresolved view method simply throws `MeshToolUnavailableException`, surfacing as an ordinary tool error. To get the pre-invoke structured refusal for a capability, either declare it as a `@MeshTool` dependency slot (`dependencies = @Selector(...)`), or pass the view as a `@MeshTool` parameter (see [Views as tool parameters](#views-as-tool-parameters) above) — the view's edges become tool-declared and its `required` methods join that tool's guard.

The optional `@McpMeshService(minAvailable = N)` adds a consumer-local availability floor: when fewer than `N` of the view's methods currently resolve, **every** facade call fails with `MeshServiceUnavailableException` — synchronous methods throw, `CompletableFuture` methods return a failed future (settle-grace-aware). The default `0` means no floor — each method soft- or hard-fails per its own `required` flag.

A service view is **consumer-local**, not a shared contract: two consumers may aggregate the same capabilities differently, and there is no group versioning or interface-level availability summary. Each method resolves independently.

**Calling-job identity through the facade.** Invoking a view facade method — or a dotted capability wired via `@MeshInject` — threads the calling-job identity / `MeshCallContext` to the provider exactly like an ordinary tool call (the same `McpMeshToolProxy` → client path). A downstream claim fence or `callingJob()` therefore sees the same caller whether the call arrives via the facade, a dotted `@MeshInject`, or a hand-written `@MeshTool` dependency. See `meshctl man jobs --java` for calling-job identity details.

### Publishing the dotted capabilities a view binds

A view is consumer-side only — it aggregates capabilities, it does not publish them. The dotted capabilities it binds are ordinary mesh tools, each declared explicitly on its provider with a dot-namespaced `@MeshTool(capability = ...)`:

```java
@Component
public class MediaProvider {
    @MeshTool(capability = "media.caption")
    public CaptionResult caption(CaptionRequest req) { ... }              // → capability "media.caption"

    @MeshTool(capability = "media.thumbnail")
    public ThumbnailResult thumbnail(ThumbnailRequest req) { ... }        // → capability "media.thumbnail"

    @MeshTool(capability = "media.transcribe", tags = {"gpu"})
    public TranscriptResult transcribe(TranscribeRequest req) { ... }     // → capability "media.transcribe"
}
```

- Each dotted `capability` is segment-validated at boot (each dot-separated segment `^[a-zA-Z][a-zA-Z0-9_-]*$`, e.g. `media.caption` or `media.v2.caption`) and resolves independently, so the three methods above can live on one bean or spread across several agents.
- Every published capability carries its own `@MeshTool` — declare each one's tags, version, description, and `outputType` where you need them.
- `meshctl list --services` groups the dotted names for display by the segments before the last dot; there is no separate service record behind the grouping.

> **Migration note — union and dotted coexist.** A legacy *union* capability (a single `session_state` tool that multiplexes several actions) and its dot-namespaced successors (`session_state.record_question_score`, `session_state.summary`, …) are **independent capabilities** — a bare name is not a hierarchical parent of the dotted ones. The same agent can publish AND consume both at once with no collision, so you can move callers onto the dotted capabilities one method at a time and remove the union tool last. That coexistence is what makes an incremental, reversible migration possible.

> **Discovery caveat.** An auto-registered facade **bean** requires `@McpMeshService` directly on the interface. An interface that only *inherits* `@McpMeshService` from a super-interface is still usable as a `@MeshTool` view parameter, but is not auto-discovered as a bean.

## `McpMeshTool<T>` API Reference

The `McpMeshTool<T>` interface is the primary way to interact with remote capabilities. The type parameter `T` indicates the expected return type.

### call() - No Arguments

Invoke the remote tool with no parameters:

```java
McpMeshTool<String> dateService;
String today = dateService.call();
```

### call(Record) - Structured Parameters

Pass a Java record whose field names become parameter names:

```java
McpMeshTool<Integer> calculator;

record AddParams(int a, int b) {}
Integer sum = calculator.call(new AddParams(3, 5));  // sum = 8
```

### call(key, value, ...) - Varargs

Pass parameters as key-value pairs:

```java
McpMeshTool<String> greeting;
String result = greeting.call("name", "Alice", "language", "en");
```

### isAvailable()

Check if the remote capability is currently reachable:

```java
if (dateService != null && dateService.isAvailable()) {
    // Safe to call
}
```

### getEndpoint()

Get the remote endpoint URL:

```java
String url = dateService.getEndpoint();
// e.g., "http://localhost:9001"
```

### getCapability()

Get the capability name this proxy represents:

```java
String cap = dateService.getCapability();
// e.g., "date_service"
```

### API Summary

| Method            | Description                        | Return Type |
| ----------------- | ---------------------------------- | ----------- |
| `call()`          | No-arg invocation                  | `T`         |
| `call(record)`    | Call with record fields as params  | `T`         |
| `call(k, v, ...)` | Call with key-value pairs          | `T`         |
| `isAvailable()`   | Check provider reachability        | `boolean`   |
| `getEndpoint()`   | Remote agent endpoint URL          | `String`    |
| `getCapability()` | Capability name of this dependency | `String`    |

## Type-Safe Responses

The generic type parameter `T` on `McpMeshTool<T>` controls response deserialization. The SDK automatically converts the remote JSON response to the specified type.

```java
// Primitive types
McpMeshTool<Integer> calculator;
Integer sum = calculator.call(new AddParams(3, 5));

// String responses
McpMeshTool<String> dateService;
String today = dateService.call();

// Complex record types
McpMeshTool<Employee> employeeService;
Employee emp = employeeService.call("id", 42);
// Employee record is auto-deserialized from JSON

record Employee(int id, String name, String department) {}
```

## Graceful Degradation

Dependencies may be unavailable if the providing agent is down or not yet started. During agent startup, calls on a declared-but-unresolved dependency first wait — bounded by the settle window (`MCP_MESH_SETTLE_TIMEOUT`, default 20s; the window starts when the agent's first dependency is declared) — for the resolution to land before degrading; once the agent settles, unresolved dependencies inject `null`/unavailable proxies immediately. Always handle `null` and check availability:

```java
@MeshTool(capability = "agent_status",
          description = "Get status with dependency info",
          dependencies = @Selector(capability = "date_service"))
public AgentStatus getStatus(McpMeshTool<String> dateService) {
    boolean depAvailable = dateService != null && dateService.isAvailable();

    if (depAvailable) {
        String date = dateService.call();
        return new AgentStatus("operational", date);
    }
    return new AgentStatus("degraded", "date service unavailable");
}

record AgentStatus(String status, String info) {}
```

Or provide fallback values:

```java
@MeshTool(capability = "time_service",
          description = "Get current time",
          dependencies = @Selector(capability = "date_service"))
public TimeResponse getTime(McpMeshTool<String> dateService) {
    if (dateService != null && dateService.isAvailable()) {
        return new TimeResponse(dateService.call());
    }
    // Fallback to local time
    return new TimeResponse(java.time.LocalDateTime.now().toString());
}
```

## Required Dependencies

By default a dependency is optional: an unresolved dependency injects a `null`/unavailable proxy, and the agent still starts, registers, and serves (soft-fail). Mark an edge `required` to opt that single edge into strictness — `@Selector(required = true)` on a `@MeshTool`, `@MeshDependency(required = true)` on a `@MeshRoute` or `@MeshDependsOn`:

```java
@MeshTool(capability = "report",
          dependencies = @Selector(capability = "data_service", required = true))
public Report generateReport(McpMeshTool<Data> dataService) { ... }

@MeshRoute(dependencies = {
    @MeshDependency(capability = "data_service", required = true)
})
@PostMapping("/report")
public ResponseEntity<Report> report(McpMeshTool<Data> dataService) { ... }
```

`required` defaults to `false` and combines with the other selector fields (`tags`, `version`, `expectedType`). It is carried on the wire only when `true`.

### Availability Semantics

The registry computes a capability-availability predicate:

> a capability is **available** ⇔ its owning agent is healthy **AND** every one of its `required` dependencies resolves to an available provider (full tag / version / schema matching)

The predicate is **transitive**: in a required chain `A → B → C`, if `C` goes down then `B` becomes unavailable and `A` becomes unavailable in turn. Optional edges never propagate — strictness flows only along edges you mark `required`, so the soft-fail default is preserved everywhere else.

An unavailable capability is excluded from resolution exactly like an unhealthy provider — it drops out at the resolver's `health` stage. Consumers holding a proxy to it see it flip to unavailable through the same background dependency-update channel that already delivers topology changes — no code changes, no SDK upgrade required.

### Route Perimeter (503)

Mesh-internal calls go through proxies; external HTTP callers to a `@MeshRoute` do not. When a route declares a required dependency that is unavailable at call time, the framework's own interceptor returns **503** — before your handler runs, after the settle window — with the body:

```json
{ "error": "dependency_unavailable", "capability": "data_service" }
```

503 rather than 404 so monitoring alarms on 5xx, load-balancer health checks eject the instance, and clients see a retryable "unavailable" instead of a permanent "missing". The required check takes precedence over the coarser `failOnMissingDependency` backstop: a required-dep 503 fires regardless of that flag, and only non-required missing deps fall through to `failOnMissingDependency`.

### Cycle Rule

A cycle among `required` edges can never converge (both ends stay unavailable forever), so the registry rejects the registration/heartbeat that would close one, loudly naming the loop:

```
required dependency cycle: analyst → enricher → analyst
```

The rejected agent logs the registration failure and keeps retrying on each heartbeat until the loop is broken. Cycles routed through an **optional** edge remain legal — that is the bootstrapping path.

### Observing Availability

The agents/capabilities API carries two derived fields per capability:

- `available` — the predicate above (boolean)
- `unavailable_reason` — set when `available` is false; names the first broken edge with its constraint detail, e.g. `required dep 'weather-api' unresolved (no provider matches tags=[+prod])`, `required dep 'data_service' unavailable (provider agent-7 unhealthy)`, or `agent unhealthy` when the owning agent is itself down.

The capability stays visible in the registry, UI, and `meshctl` (availability is distinct from presence), so the reason chain is a diagnostic upgrade, not a disappearance.

## Auto-Rewiring

When topology changes (agents join/leave), the mesh:

1. Detects change via heartbeat response
2. Refreshes dependency proxies
3. Routes to new providers automatically

No code changes needed - happens transparently.

## Multiple Dependencies

A single tool can depend on multiple capabilities. Each dependency gets its own `McpMeshTool<T>` parameter:

```java
@MeshTool(capability = "add_via_mesh",
          description = "Add two numbers using remote calculator",
          tags = {"math", "cross-agent", "java"},
          dependencies = @Selector(capability = "add"))
public CalculationResult addViaMesh(
        @Param(value = "a", description = "First number") int a,
        @Param(value = "b", description = "Second number") int b,
        McpMeshTool<Integer> calculator) {

    Integer sum = calculator.call(new AddParams(a, b));
    return new CalculationResult("add", a, b, sum);
}

record AddParams(int a, int b) {}
record CalculationResult(String op, int a, int b, int result) {}
```

### LLM Injection

For `@MeshLlm` annotated tools, the LLM is injected as a `MeshLlmAgent` parameter:

```java
@MeshLlm(providerSelector = @Selector(capability = "llm"),
         maxIterations = 5, systemPrompt = "You are a helpful analyst.")
@MeshTool(capability = "analyze",
          description = "AI-powered analysis",
          tags = {"analysis", "llm", "java"})
public AnalysisResult analyze(
        @Param(value = "query", description = "Analysis query") String query,
        MeshLlmAgent llm) {

    return llm.request()
              .user(query)
              .generate(AnalysisResult.class);
}
```

## Complete Example

```java
package com.example.assistant;

import io.mcpmesh.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "assistant", version = "1.0.0",
           description = "Assistant with mesh dependencies", port = 9001)
@SpringBootApplication
public class AssistantAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(AssistantAgentApplication.class, args);
    }

    @MeshTool(capability = "smart_greeting",
              description = "Greet with current date from mesh",
              tags = {"greeting", "assistant", "java"},
              dependencies = @Selector(capability = "date_service"))
    public GreetingResponse smartGreet(
            @Param(value = "name", description = "The name to greet") String name,
            McpMeshTool<String> dateService) {

        if (dateService != null && dateService.isAvailable()) {
            String dateString = dateService.call();
            return new GreetingResponse(
                "Hello, " + name + "! Today is " + dateString);
        }
        return new GreetingResponse(
            "Hello, " + name + "! (date service unavailable)");
    }

    @MeshTool(capability = "agent_status",
              description = "Get agent status with dependency info",
              tags = {"status", "info", "java"},
              dependencies = @Selector(capability = "date_service"))
    public AgentStatus getStatus(McpMeshTool<String> dateService) {
        boolean available = dateService != null && dateService.isAvailable();
        String endpoint = available ? dateService.getEndpoint() : "N/A";
        String capability = available ? dateService.getCapability() : "N/A";

        return new AgentStatus("assistant", available, endpoint, capability);
    }

    record GreetingResponse(String message) {}
    record AgentStatus(String agent, boolean depAvailable,
                       String depEndpoint, String depCapability) {}
}
```

## See Also

- `meshctl man capabilities --java` - Declaring capabilities
- `meshctl man tags --java` - Tag-based selection
- `meshctl man schema-matching` - Schema-aware capability filtering (#547)
- `meshctl man audit` - Inspecting resolution decisions
- `meshctl man decorators --java` - All Java annotations
