<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/dependency-injection/">Python Dependency Injection</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/dependency-injection/">TypeScript Dependency Injection</a></span>
</div>

# Dependency Injection (Java/Spring Boot)

> Automatic wiring of capabilities between agents

MCP Mesh implements **[Distributed Dynamic Dependency Injection (DDDI)](../concepts/dddi.md)** — dependencies are discovered and injected at runtime across the mesh, not at compile time.

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a tool declares a dependency via `@Selector`, the mesh automatically injects a `McpMeshTool<T>` proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Tool declares dependencies via `@MeshTool(dependencies = @Selector(...))`
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh injects `McpMeshTool<T>` instances as method parameters
5. **Invocation**: Calling the proxy routes to the remote agent

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

### Required, optional, and the availability floor

`required = true` on a view method behaves like a class-level `@MeshDependsOn` required dependency (see [Required Dependencies](#required-dependencies) below): it participates in cross-source required-wins dedupe, flips the registry-side availability of that capability's carrier when unresolved (visible in `meshctl list` and the registry API), and promotes any matching route-perimeter 503 guard. An optional method whose provider is down throws `MeshToolUnavailableException` on **that call only**; catch it for graceful degradation while the rest of the view keeps working.

!!! note "One difference when injected as a bean"
    An autowired view facade is class-level, so the framework cannot know which `@MeshTool` methods call it and does **not** add a pre-invoke structured `dependency_unavailable` refusal to those tools — a call to a required-but-unresolved view method simply throws `MeshToolUnavailableException`, surfacing as an ordinary tool error. To get the pre-invoke structured refusal for a capability, either declare it as a `@MeshTool` dependency slot (`dependencies = @Selector(...)`), or pass the view as a `@MeshTool` parameter (see [Views as tool parameters](#views-as-tool-parameters) above) — the view's edges become tool-declared and its `required` methods join that tool's guard.

The optional `@McpMeshService(minAvailable = N)` adds a consumer-local availability floor: when fewer than `N` of the view's methods currently resolve, **every** facade call fails with `MeshServiceUnavailableException` — synchronous methods throw, `CompletableFuture` methods return a failed future (settle-grace-aware). The default `0` means no floor — each method soft- or hard-fails per its own `required` flag.

A service view is **consumer-local**, not a shared contract: two consumers may aggregate the same capabilities differently, and there is no group versioning or interface-level availability summary. Each method resolves independently.

### Publishing a service (producer side)

The same annotation works on the **provider** side too. Put class-level `@McpMeshService("prefix")` on a Spring bean and each eligible public method is published as an ordinary mesh tool under the capability `prefix.<methodName>` — pure sugar over writing one `@MeshTool` per method.

```java
@Component
@McpMeshService("media")
public class MediaProvider {
    public CaptionResult   caption(CaptionRequest req)     { ... }   // → capability "media.caption"
    public ThumbnailResult thumbnail(ThumbnailRequest req) { ... }   // → capability "media.thumbnail"

    @MeshTool(capability = "transcribe_gpu", tags = {"gpu"})          // custom name — @MeshTool overrides the prefix.<method> derivation
    public TranscriptResult transcribe(TranscribeRequest req) { ... }
}
```

- The `prefix` is entirely yours, segment-validated at boot (each dot-separated segment `^[a-zA-Z][a-zA-Z0-9_-]*$`, e.g. `media` or `media.v2`). The blank default `@McpMeshService` marks a consumer view and boot-fails on a producer class.
- Methods publish in **name-sorted** order. Only **public, instance** methods **declared on the class itself** are published — non-public, `static`, `Object`, and inherited-from-superclass methods are skipped.
- An **explicit `@MeshTool`** on a method wins — use it whenever a method needs a custom capability, tags, version, or description; producer sugar synthesizes none of those.
- **Overloaded** public methods collide on `prefix.<name>` and boot-fail: rename one, make one non-public, or give one an explicit `@MeshTool`.
- `minAvailable` is a consumer-view attribute; on a producer class it logs a WARN and is ignored. A `@McpMeshService` class that Spring doesn't manage as a bean WARNs at scan time and publishes nothing.

!!! note "Discovery caveat"
    An auto-registered facade **bean** requires `@McpMeshService` directly on the interface. An interface that only *inherits* `@McpMeshService` from a super-interface is still usable as a `@MeshTool` view parameter, but is not auto-discovered as a bean.

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

Dependencies may be unavailable if the providing agent is down or not yet started. Always handle `null` and check availability:

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

Graceful degradation is the default — an unresolved dependency injects a `null`/unavailable proxy and your agent keeps serving. When a capability is useless without a particular dependency, mark that edge `required` instead of checking `isAvailable()` everywhere. Use `required = true` on `@Selector` (tools) or `@MeshDependency` (routes / `@MeshDependsOn`):

```java
@MeshTool(capability = "report",
          description = "Generate a report from mesh data",
          dependencies = @Selector(capability = "data_service", required = true))
public Report generateReport(McpMeshTool<Data> dataService) {
    // dataService is guaranteed live — no isAvailable() check needed
    return new Report(dataService.call());
}
```

`required` defaults to `false` and combines with the other selector fields (`tags`, `version`, `expectedType`).

**What it changes.** The registry now computes a capability as **available** only when its owning agent is healthy *and* every one of its `required` dependencies resolves to an available provider. This is transitive — in a chain `A → B → C`, if `C` goes down then `B` becomes unavailable and `A` becomes unavailable in turn. An unavailable capability drops out of resolution exactly like an unhealthy provider, so any consumer's proxy for it flips to unavailable automatically, with no code change. Optional edges never propagate, so soft-fail stays the default everywhere you don't opt in.

**HTTP routes get an automatic 503.** External callers to a `@MeshRoute` don't go through proxies, so when a route declares a required dependency that is unavailable at request time, the framework returns `503` before your handler runs (after the settle window):

```java
@GetMapping("/report")
@MeshRoute(dependencies = @MeshDependency(capability = "data_service", required = true))
public ResponseEntity<Report> report(McpMeshTool<Data> dataService) {
    return ResponseEntity.ok(new Report(dataService.call()));
}
```

The response body is `{"error":"dependency_unavailable","capability":"data_service"}`. This required check takes precedence over the coarser `failOnMissingDependency` flag — a required-dep 503 fires regardless of that flag, and only non-required missing deps fall through to it.

**Cycles are rejected.** A cycle of required edges could never converge (both ends stay unavailable forever), so the registry rejects the registration that closes one and logs, on the rejected agent, a `required dependency cycle: analyst → enricher → analyst` registration failure. Cycles that route through an optional edge remain legal — that's the bootstrapping path.

**Inspecting availability.** Each capability in the agents/capabilities API carries `available` (boolean) and, when false, `unavailable_reason` naming the first broken edge — e.g. `required dep 'data_service' unavailable (provider agent-7 unhealthy)` or `required dep 'weather-api' unresolved (no provider matches tags=[+prod])`. The capability stays visible in the registry, UI, and `meshctl`; availability is distinct from presence.

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
- `meshctl man decorators --java` - All Java annotations
